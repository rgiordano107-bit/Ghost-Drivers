import pandas as pd
import numpy as np
import os
from sklearn.model_selection import train_test_split
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Dense, Dropout, Input, concatenate
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

# 1. CARICAMENTO DATASET E GESTIONE DAGGER
print("Caricamento del dataset in corso...")
df_originale = pd.read_csv('dataset.csv')

soglia_rettilineo = 0.02

df_rettilinei = df_originale[abs(df_originale['steer']) < soglia_rettilineo].copy() #copy() viene usato per evitare possibili warning

df_rettilinei['steer'] = 0.0 #Nei rettilinei lo sterzo viene azzerato per evitare rumore nei dati

df_curve = df_originale[abs(df_originale['steer']) >= soglia_rettilineo]

print(f"Prima del bilanciamento: {len(df_rettilinei)} rettilinei, {len(df_curve)} curve.")

# Calcoliamo la frazione esatta per pareggiare le curve
if len(df_rettilinei) > 0:
    frazione_bilanciamento = min(1.0, len(df_curve) / len(df_rettilinei))
else:
    frazione_bilanciamento = 1.0

df_rettilinei_ridotto = df_rettilinei.sample(frac=frazione_bilanciamento, random_state=42) # Undersampling dei rettilinei per bilanciare il dataset

# Ricostruzione del dataset bilanciato
df_originale = pd.concat([df_rettilinei_ridotto, df_curve], ignore_index=True)
print(f"Dopo il bilanciamento: {len(df_rettilinei_ridotto)} rettilinei, {len(df_curve)} curve.")

file_dagger = 'dagger_data.csv'

# Controlliamo se esiste il file con i dati correttivi di DAgger
if os.path.exists(file_dagger):
    print(f"Trovato file DAgger: '{file_dagger}'.")
    df_dagger = pd.read_csv(file_dagger)
    
    # Uniamo i due dataset
    df = pd.concat([df_originale, df_dagger], ignore_index=True)
    pesi = np.ones(len(df))
    
    # Peso di DAgger (Non troppo alto per evitare overfitting)
    peso_dagger = min(len(df_originale) / len(df_dagger), 3.5)
    inizio_dagger = len(df_originale)
    pesi[inizio_dagger:] = peso_dagger
    
    print(f"Dimensione dataset unito: {len(df)} righe.")
else:
    print(f"Nessun file '{file_dagger}' trovato. Addestramento base sul dataset originale.")
    df = df_originale
    pesi = np.ones(len(df))

# 2. NORMALIZZAZIONE DEI DATI
df['angle'] = df['angle'] / 3.14159
df['speedX'] = df['speedX'] / 300.0
for i in range(19):
    df[f'track_{i}'] = df[f'track_{i}'] / 200.0

feature_cols = ['angle', 'trackPos', 'speedX'] + [f'track_{i}' for i in range(19)]
X = df[feature_cols].values

target_cols = ['steer', 'accel', 'brake']
y = df[target_cols].values

# 3. DIVISIONE TRAIN / VALIDATION ---
X_train, X_val, y_train, y_val, pesi_train, pesi_val = train_test_split(
    X, y, pesi, test_size=0.2, random_state=42
)

# 4. CREAZIONE RETE NEURALE
# Input a singolo frame (22 features)
inputs = Input(shape=(X_train.shape[1],))

# La rete è composta da 3 layer densi con dropout per evitare overfitting, seguiti da due rami di output: uno per lo sterzo e uno per i pedali
x = Dense(128, activation='relu')(inputs)
x = Dropout(0.2)(x)
x = Dense(64, activation='relu')(x)
x = Dropout(0.1)(x)
x = Dense(32, activation='relu')(x)

# Ramo Sterzo
steer_out = Dense(1, activation='tanh', name='steer')(x)
# Ramo Pedali
pedals_out = Dense(2, activation='sigmoid', name='pedals')(x)

outputs = concatenate([steer_out, pedals_out])
model = Model(inputs=inputs, outputs=outputs)

# 5. COMPILAZIONE E ADDESTRAMENTO
model.compile(optimizer='adam', loss='mse', metrics=['mae'])
early_stop = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
checkpoint = ModelCheckpoint('modello_bc.h5', monitor='val_loss', save_best_only=True)

print("Inizio addestramento...")
model.fit(
    X_train, y_train,
    sample_weight=pesi_train,
    validation_data=(X_val, y_val, pesi_val),
    epochs=100,
    batch_size=256,
    callbacks=[early_stop, checkpoint]
)
print("Addestramento completato. Modello salvato come 'modello_bc.h5'")
