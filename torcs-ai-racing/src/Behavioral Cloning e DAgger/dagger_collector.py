import numpy as np
import tensorflow as tf
from tensorflow.keras.models import load_model
import sys
import os
import csv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snakeoil

MODELLO_BC = 'modello_bc.h5'
NUOVO_DATASET = 'dagger_data.csv'

def estrai_stato_scalato(S):
    angle = float(S.get("angle", 0.0)) / 3.14159
    trackPos = float(S.get("trackPos", 0.0))
    speedX = float(S.get("speedX", 0.0)) / 300.0
    
    track_raw = S.get("track", [200.0] * 19)
    if not isinstance(track_raw, list) or len(track_raw) < 19:
        track_raw = [200.0] * 19
    
    features_grezze = [float(S.get("angle", 0.0)), trackPos, float(S.get("speedX", 0.0))] + [float(t) for t in track_raw]
    features_scalate = [angle, trackPos, speedX] + [float(t) / 200.0 for t in track_raw]
    
    return np.array([features_scalate], dtype=np.float32), features_grezze
    
def bot_esperto_a_regole(S):
    speed = float(S.get("speedX", 0.0))
    angle = float(S.get("angle", 0.0))
    track_pos = float(S.get("trackPos", 0.0))
    
    track = S.get("track", [200.0] * 19)
    if not isinstance(track, list) or len(track) < 19:
        track = [200.0] * 19

    # Sensori frontali e laterali
    front = (track[8] + track[9] + track[10]) / 3.0
    left_front = sum(track[2:8]) / 6.0   # Allargato leggermente lo spettro visivo
    right_front = sum(track[11:17]) / 6.0

    # Segnale di curva (anticipazione spaziale)
    curve_signal = (left_front - right_front) / max(1.0, left_front + right_front)
    curve_intensity = 1.0 - min(front, 200.0) / 200.0

    is_slight_curve = front > 75 and abs(curve_signal) < 0.30
    is_straight = front > 100 and abs(curve_signal) < 0.10

    if is_straight and front >= 140:
        target_speed = 300 # Abbassata leggermente la target speed per affrontare meglio le curve
    else:
        # Se ci troviamo in curva
        if front < 40: 
            target_speed = 45  # In caso di doppia curva corkscrew o comunque una curva molto stretta
        elif front > 85: 
            target_speed = 250
        else: 
            target_speed = 45 + (front - 40) * (250 - 45) / (140 - 40) 

        if not is_slight_curve:
            target_speed -= abs(curve_signal) * 15  # Rallenta proporzionalmente all'intensità della curva
            target_speed -= abs(angle) * 10
            target_speed -= abs(track_pos) * 5

    target_speed = np.clip(target_speed, 40, 300)

    damping_factor = max(0.15, 1.0 - (speed / 280.0)) # Lo sterzo viene smorzato progressivamente all'aumentare della velocità 

   
    if is_straight:
        if abs(track_pos) < 0.25 and abs(angle) < 0.04:
            steer = angle * 0.8
        else:
            steer = angle * (0.50 * damping_factor) - track_pos * 0.1
    else:
        ideal_pos = -curve_signal * 0.40 if front > 65 else curve_signal * 0.95  
        error_pos = track_pos - ideal_pos 

        if is_slight_curve and speed > 150:
            steer = angle * (0.8 * damping_factor) - error_pos * 0.4 + curve_signal * 0.6
        else:
            steer = angle * (1.6 * damping_factor) - error_pos * (1.2 * damping_factor) + curve_signal * 1.8 + curve_signal * curve_intensity * 1.2

    # Limiti fisici dello sterzo 
    if is_straight and abs(angle) < 0.05:
        steer = np.clip(steer, -0.01, 0.01) if speed > 200 else np.clip(steer, -0.02, 0.02) if speed > 120 else np.clip(steer, -1.0, 1.0)
    else:
        steer = np.clip(steer, -0.18, 0.18) if speed > 220 else np.clip(steer, -0.35, 0.35) if speed > 150 else np.clip(steer, -0.80, 0.80) if speed > 80 else np.clip(steer, -1.0, 1.0)

    # LOGICA PEDALI
    accel, brake = 0.0, 0.0
    
    if speed < target_speed - 10: 
        accel = 1.0       
    elif speed <= target_speed + 5: 
        accel, brake = 0.50, 0.0
    else: 
        # Freno più reattivo
        brake = np.clip((speed - target_speed) / 35.0, 0.1, 1.0)  

    # FRENATA DI EMERGENZA (doppia curva corkscrew)
    if front < 60 and speed > 80 and not is_straight: 
        accel, brake = 0.0, 1.0  # Inchioda!
        
    if abs(angle) > 0.65: 
        accel *= 0.10
        brake = max(brake, 0.50)
        
    if abs(track_pos) > 1.0: 
        accel, brake = 0.40, 0.20 # Cerca di rientrare piano

    # Controllo trazione
    wheel = S.get("wheelSpinVel", [0.0, 0.0, 0.0, 0.0])
    if isinstance(wheel, list) and len(wheel) >= 4:
        slip = (wheel[2] + wheel[3]) - (wheel[0] + wheel[1])
        if slip > 5.0 and speed > 40: 
            accel *= 0.80 if is_straight else 0.0 

    return float(np.clip(steer, -1.0, 1.0)), float(np.clip(accel, 0.0, 1.0)), float(np.clip(brake, 0.0, 1.0))

def avvia_dagger():
    print("=== AVVIO RACCOLTA DATI DAGGER (Definitiva) ===")
    modello = load_model(MODELLO_BC, compile=False)
    
    file_esiste = os.path.isfile(NUOVO_DATASET)
    with open(NUOVO_DATASET, mode='a', newline='') as file_csv:
        writer = csv.writer(file_csv)
        if not file_esiste:
            header = ['angle', 'trackPos', 'speedX'] + [f'track_{i}' for i in range(19)] + ['steer', 'accel', 'brake']
            writer.writerow(header)

        client = snakeoil.Client(p=3001)
        print("[OK] Connesso. La Rete Neurale guida da sola, l'Esperto annota e corregge gli errori...")
        
        frame_in_stallo = 0
        frame_totali = 0
        sterzo_precedente = 0.0
        
        salvataggio_ogni_n_frame = 3  # Salva meno frequentemente
        
        try:
            while True:
                client.get_servers_input()
                S = client.S.d
                frame_totali += 1
                
                track_pos = abs(float(S.get("trackPos", 0.0)))
                speed = float(S.get("speedX", 0.0))
                
                if track_pos > 1.5:
                    print(f"\n[STOP] Auto fuori pista (TrackPos: {track_pos:.2f}).")
                    break
                    
                if speed < 5.0 and frame_totali > 50: frame_in_stallo += 1
                else: frame_in_stallo = 0
                    
                if frame_in_stallo > 100:
                    print("\n[STOP] Auto incastrata o in testacoda.")
                    break
                
                stato_scalato, features_grezze = estrai_stato_scalato(S)
                azione_ai = modello(stato_scalato, training=False)[0].numpy()
                expert_steer, expert_accel, expert_brake = bot_esperto_a_regole(S)
                
                riga_csv = features_grezze + [expert_steer, expert_accel, expert_brake]
                
                track_raw = S.get("track", [200.0] * 19)
                if isinstance(track_raw, list) and len(track_raw) >= 19:
                    front_dist = (track_raw[8] + track_raw[9] + track_raw[10]) / 3.0
                    angle = float(S.get("angle", 0.0))
                    
                    condizione_dagger = front_dist < 120.0 or abs(angle) > 0.08 or track_pos > 0.2 # Condizioni per attivare DAgger
                    condizione_pista = track_pos < 1.0 # Filtro anti-erba (non salva quando l'auto è già fuori pista)
                    
                    if condizione_pista:
                        if condizione_dagger:
                            # Salviamo molto nelle curve e nelle emergenze
                            if frame_totali % salvataggio_ogni_n_frame == 0:
                                writer.writerow(riga_csv)
                        else:
                            # Salviamo 1 frame ogni 15 anche in rettilineo perfetto
                            # per ricordare alla rete come si va dritti senza oscillare.
                            if frame_totali % 15 == 0:
                                writer.writerow(riga_csv)
                

                # CONTROLLO ALLA GUIDA 
                if speed < 20.0:
                    client.R.d['steer'], client.R.d['accel'], client.R.d['brake'] = 0.0, 0.35, 0.0 # Serve solo per la prima iterazione dell'algoritmo DAgger
                else:
                    sterzo_ai_grezzo = float(np.clip(azione_ai[0], -1.0, 1.0))
                    
                    sterzo_fluido = (0.7 * sterzo_precedente) + (0.3 * sterzo_ai_grezzo)
                    sterzo_precedente = sterzo_fluido
                    
                    client.R.d['steer'] = sterzo_fluido
                    client.R.d['accel'] = float(np.clip(azione_ai[1], 0.0, 1.0))
                    client.R.d['brake'] = float(np.clip(azione_ai[2], 0.0, 1.0))
                
                client.R.d['gear'] = 1 if speed < 40 else 2 if speed < 85 else 3 if speed < 135 else 4 if speed < 185 else 5 if speed < 245 else 6 # Gestione delle marce in base alla velocità
                client.respond_to_server()
                
        except KeyboardInterrupt:
            print("\nRaccolta DAgger interrotta.")
        finally:
            client.shutdown()

if __name__ == "__main__":
    avvia_dagger()