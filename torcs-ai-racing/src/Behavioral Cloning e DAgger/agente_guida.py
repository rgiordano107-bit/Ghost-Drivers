import numpy as np
import tensorflow as tf
from tensorflow.keras.models import load_model
import sys
import os
import csv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snakeoil

MODELLO_BC = 'modello_bc.h5'

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
    

def avvia_guida():
    modello = load_model(MODELLO_BC, compile=False)
    
    client = snakeoil.Client(p=3001)
    print("[OK] Connesso.")
        
    frame_in_stallo = 0
    frame_totali = 0
    sterzo_precedente = 0.0
           
    try:
         while True:
                client.get_servers_input()
                S = client.S.d
                
                
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
                    
                # --- CONTROLLO ALLA GUIDA ---
                if speed < 20.0:
                    client.R.d['steer'], client.R.d['accel'], client.R.d['brake'] = 0.0, 0.35, 0.0
                else:
                    sterzo_ai_grezzo = float(np.clip(azione_ai[0], -1.0, 1.0))
                    
                    sterzo_fluido = (0.7 * sterzo_precedente) + (0.3 * sterzo_ai_grezzo)
                    sterzo_precedente = sterzo_fluido
                    
                    client.R.d['steer'] = sterzo_fluido
                    client.R.d['accel'] = float(np.clip(azione_ai[1], 0.0, 1.0))
                    client.R.d['brake'] = float(np.clip(azione_ai[2], 0.0, 1.0))
                
                client.R.d['gear'] = 1 if speed < 40 else 2 if speed < 85 else 3 if speed < 135 else 4 if speed < 185 else 5 if speed < 245 else 6
                client.respond_to_server()
                
    except KeyboardInterrupt:
            print("\nGara interrotta.")
    finally:
            client.shutdown()

if __name__ == "__main__":
    avvia_guida()