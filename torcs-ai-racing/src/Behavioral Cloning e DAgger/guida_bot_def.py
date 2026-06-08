import snakeoil
import csv
import sys
import random
import os

NOME_FILE = 'dataset.csv'
USA_RUMORE = True

def clip(v, lo, hi):
    if v < lo: return lo
    elif v > hi: return hi
    else: return v

def automatic_gear(speed):
    if speed < 40: return 1
    elif speed < 85: return 2
    elif speed < 135: return 3
    elif speed < 185: return 4 #180
    elif speed < 245: return 5 #250
    else: return 6

def get_track_sensors(S):
    track = S.get("track", [200.0] * 19)
    if not isinstance(track, list) or len(track) < 19:
        track = [200.0] * 19
    return track

def drive_and_collect(c, data_buffer):
    S, R = c.S.d, c.R.d

    speed = float(S.get("speedX", 0.0))
    angle = float(S.get("angle", 0.0))
    track_pos = float(S.get("trackPos", 0.0))
    track = get_track_sensors(S)

    front = (track[8] + track[9] + track[10]) / 3.0
    left_front = sum(track[3:9]) / 6.0
    right_front = sum(track[10:16]) / 6.0

    curve_signal = (left_front - right_front) / max(1.0, left_front + right_front)
    curve_intensity = 1.0 - min(front, 200.0) / 200.0

    is_slight_curve = front > 75 and abs(curve_signal) < 0.30
    is_straight = front > 100 and abs(curve_signal) < 0.10

    # CONDIZIONI SULLA TARGET SPEED - Usiamo un'interpolazione lineare per addolcire il passaggio da una velocità e l'altra
    if is_straight and front >= 140:
        target_speed = 400
    else:
        # Nelle curve la velocità desiderata è 95 km/h
        if front < 40:
            target_speed = 95
        elif front > 85:
            target_speed = 300
        else:
            target_speed = 95 + (front - 40) * (370 - 95) / (140 - 40)

        #Frena di meno nelle curve leggere, ma riduce la velocità nelle curve più strette
        if not is_slight_curve:
            target_speed -= abs(curve_signal) * 8  
            target_speed -= abs(angle) * 5
            target_speed -= abs(track_pos) * 3

    target_speed = clip(target_speed, 75, 400)

    # CONDIZIONI SULLO STERZO 
    damping_factor = max(0.15, 1.0 - (speed / 280.0))

    if is_straight:
        if front > 120 and speed > 100:
            if abs(angle) < 0.04:
                steer = 0.0  
            else:
                steer = angle * 0.02
                steer = clip(steer, -0.01, 0.01)
        else:
            # Per allargare dolcemente in approccio alla staccata
            steer = angle * (0.40 * damping_factor) - track_pos * 0.005
    else:
        # Utilizzo della tecnica Out-In, e In per le curve più strette 
        if front > 65:
            # Se la curva è ancora lontana, allarga la traiettoria (OUT)
            ideal_pos = -curve_signal * 0.30 
        else:
            # Se è dentro la curva, stringe al massimo il cordolo (IN)
            ideal_pos = curve_signal * 0.95  
            
        error_pos = track_pos - ideal_pos # Valutazione dell'errore rispetto alla traiettoria ideale  

        if is_slight_curve and speed > 150:
            steer = angle * (0.8 * damping_factor)
            steer -= error_pos * 0.4
            steer += curve_signal * 0.6
        else:
            steer = angle * (1.6 * damping_factor)           
            steer -= error_pos * (1.2 * damping_factor)      
            steer += curve_signal * 1.3   
            steer += curve_signal * curve_intensity * 0.8

    
    # LIMITATORE DINAMICO: in base alla situazione (sterzo limitato nelle alte velocità)
    if is_straight and abs(angle) < 0.05:
        if speed > 200: steer = clip(steer, -0.01, 0.01) 
        elif speed > 120: steer = clip(steer, -0.02, 0.02) 
        else: steer = clip(steer, -1.0, 1.0)
    else:
        # Volante leggermente più libero per le curve veloci
        if speed > 220: steer = clip(steer, -0.18, 0.18)
        elif speed > 150: steer = clip(steer, -0.35, 0.35)
        elif speed > 100: steer = clip(steer, -0.60, 0.60)
        else: steer = clip(steer, -1.0, 1.0)


    # PEDALI: SCORRIMENTO VELOCE E TRAIL BRAKING
    accel = 0.0
    brake = 0.0

    if speed < 40 and front > 50:
        accel = 1.0
    elif speed < target_speed - 15: 
        accel = 1.0       
    elif speed <= target_speed + 15: 
        # Più gas per portare velocità, ma un 2% di freno per mantenere stabilità
        accel = 0.50  
        brake = 0.02
    else: 
        eccesso_velocita = speed - target_speed
        # Frenata dolce, limite superiore per evitare perdita di controllo
        brake = clip(eccesso_velocita / 65.0, 0.05, 0.65)  

    if front < 25 and speed > 60 and not is_straight:
        accel = 0.0; brake = 0.90  

    if abs(angle) > 0.65:
        accel *= 0.30; brake = max(brake, 0.20)
    if abs(track_pos) > 1.0:
        accel = 0.40; brake = 0.0 # Spinge un po' di più per uscire dall'erba

    # CONTROLLO DELLA TRAZIONE
    wheel = S.get("wheelSpinVel", [0.0, 0.0, 0.0, 0.0])
    if isinstance(wheel, list) and len(wheel) >= 4:
        slip = (wheel[2] + wheel[3]) - (wheel[0] + wheel[1])
        if slip > 5.0 and speed > 40:
            if is_straight: accel *= 0.90
            else: accel *= 0.10 

   
    # INIEZIONE DEL RUMORE NELLE CURVE LEGGERE AD ALTA VELOCITÀ 
    steer_perfetto = clip(steer, -1.0, 1.0)
    steer_applicato = steer_perfetto
    
    if USA_RUMORE and not (is_straight and speed > 100):
        if random.random() < 0.05:
            rumore = random.uniform(-0.15, 0.15)
            steer_applicato = clip(steer_perfetto + rumore, -1.0, 1.0)

    R["steer"] = steer_applicato
    R["accel"] = clip(accel, 0.0, 1.0)
    R["brake"] = clip(brake, 0.0, 1.0)
    R["gear"] = automatic_gear(speed)

    dati_riga = [angle, track_pos, speed] + track + [steer_perfetto, R["accel"], R["brake"]]
    data_buffer.append(dati_riga)


if __name__ == "__main__":
    print("RACCOLTA DATI")
    print(f"File in uso: '{NOME_FILE}'. Premi CTRL+C per fermare.\n")
    
    file_esiste = os.path.isfile(NOME_FILE)
    
    buffer_dati_ram = [] #Scrittura in RAM durante la gara, per evitare rallentamenti dovuti ad interruzioni di I/O su disco.
    # Il file poi viene aggiornato ogni 250 righe o in caso di interruzione da tastiera (Ctrl+C)
    
    with open(NOME_FILE, mode='a', newline='') as file_csv:
        writer = csv.writer(file_csv)
        
        if not file_esiste:
            intestazione = ['angle', 'trackPos', 'speedX'] + [f'track_{i}' for i in range(19)] + ['steer', 'accel', 'brake']
            writer.writerow(intestazione)
        
        C = snakeoil.Client(p=3001)
        try:
            for step in range(C.maxSteps, 0, -1):
                C.get_servers_input()
                drive_and_collect(C, buffer_dati_ram)
                C.respond_to_server()

                if len(buffer_dati_ram) >= 250:
                    writer.writerows(buffer_dati_ram)
                    buffer_dati_ram.clear()
                    
        except KeyboardInterrupt:
            if buffer_dati_ram:
                writer.writerows(buffer_dati_ram)
            print(f"\nDataset aggiornato e salvato in: {NOME_FILE}")
        finally:
            C.shutdown()