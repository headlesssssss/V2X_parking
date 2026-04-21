import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report
import joblib

CSV_PATH   = "C:/Users/othma/OneDrive/Desktop/PFA/SmartParking/mock_rsu/dataset_parking.csv"
MODEL_PATH = "C:/Users/othma/OneDrive/Desktop/PFA/SmartParking/server/isolation_forest.pkl"

print("=" * 60)
print("  Entraînement Isolation Forest — Features enrichies")
print("=" * 60)

df = pd.read_csv(CSV_PATH)
df = df.sort_values(["place_id", "timestamp"]).reset_index(drop=True)

print(f"\n[DATA]  Lignes chargees  : {len(df)}")
print(f"[DATA]  Anomalies        : {df['est_anomalie'].sum()} ({df['est_anomalie'].mean()*100:.1f}%)")
print(f"[DATA]  Normales         : {(df['est_anomalie']==0).sum()}")

print("\n[FEAT]  Calcul des features...")
features_list = []

for place_id, groupe in df.groupby("place_id"):
    distances = groupe["distance_cm"].values
    labels    = groupe["est_anomalie"].values

    for i in range(len(distances)):
        dist   = distances[i]
        window = distances[max(0, i-10):i+1]
        f2     = float(np.std(window)) if len(window) > 1 else 0.0
        f3     = abs(float(dist) - float(distances[i-1])) if i > 0 else 0.0

        features_list.append({
            "place_id":    place_id,
            "distance_cm": dist,
            "std_10":      round(f2, 4),
            "delta":       round(f3, 4),
            "label":       labels[i]
        })

df_feat = pd.DataFrame(features_list)
print(f"[FEAT]  Features calculees pour {len(df_feat)} mesures")
print(f"\n[FEAT]  Apercu :")
print(df_feat[["distance_cm","std_10","delta","label"]].describe().round(3))

normales = df_feat[df_feat["label"] == 0][["distance_cm","std_10","delta"]].values
contamination = round(float(df_feat["label"].mean()), 3)

print(f"\n[ML]   Contamination : {contamination}")
print("[ML]   Entraînement en cours...")

modele = IsolationForest(
    n_estimators=200,
    contamination=contamination,
    random_state=42
)
modele.fit(normales)
print("[ML]   Entraînement termine !")

X_all  = df_feat[["distance_cm","std_10","delta"]].values
y_true = df_feat["label"].values
y_pred = (modele.predict(X_all) == -1).astype(int)

print("\n[ML]   Rapport de classification :")
print(classification_report(y_true, y_pred, target_names=["Normal","Anomalie"]))

joblib.dump(modele, MODEL_PATH)
print(f"[ML]   Modele sauvegarde : {MODEL_PATH}")

print("\n[ML]   Tests de validation :")
print("-" * 60)

def tester(dist, std, delta, desc):
    pred   = modele.predict([[dist, std, delta]])[0]
    score  = modele.score_samples([[dist, std, delta]])[0]
    statut = "ANOMALIE" if pred == -1 else "NORMAL  "
    print(f"  dist={dist:>5}cm  std={std:>5}  delta={delta:>5}  [{statut}]  score={score:>7.4f}  — {desc}")

tester(2.0,  0.05, 0.1, "Place occupee stable — normal")
tester(7.0,  0.08, 0.2, "Place libre stable — normal")
tester(2.2,  0.10, 0.3, "Place occupee avec bruit — normal")
tester(6.8,  0.12, 0.4, "Place libre avec bruit — normal")
tester(0.3,  0.02, 0.1, "Capteur mort — anomalie")
tester(12.0, 0.05, 0.1, "Hors portee — anomalie")
tester(4.5,  0.00, 0.0, "Valeur completement figee — anomalie")
tester(2.0,  3.50, 5.5, "Oscillation brutale — anomalie")
tester(7.0,  2.80, 4.8, "Instabilite forte — anomalie")

print("=" * 60)
print("[ML]   Modele pret : isolation_forest.pkl")