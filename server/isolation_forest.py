import numpy as np
from sklearn.ensemble import IsolationForest
import json

# ── Génération des données d entraînement ──────────────────
# On simule des milliers de mesures normales de capteurs HC-SR04
# Deux types de mesures normales :
#   - Place occupée  : distance entre 5 et 25 cm
#   - Place libre    : distance entre 150 et 210 cm

np.random.seed(42)

# 1000 mesures place occupée
occupees = np.random.uniform(5, 25, 1000)

# 1000 mesures place libre
libres = np.random.uniform(150, 210, 1000)

# On combine tout
donnees_normales = np.concatenate([occupees, libres]).reshape(-1, 1)

# ── Entraînement du modèle ─────────────────────────────────
print("[ML]  Entraînement du modèle Isolation Forest...")
modele = IsolationForest(
    n_estimators=100,     # 100 arbres de décision
    contamination=0.05,   # on suppose 5% d anomalies max
    random_state=42
)
modele.fit(donnees_normales)
print("[ML]  Modèle entraîné avec succes !")

# ── Fonction de détection ──────────────────────────────────
def est_anomalie(distance_cm: float) -> bool:
    """
    Retourne True si la distance est anormale.
    Retourne False si la distance est normale.
    """
    valeur = np.array([[distance_cm]])
    prediction = modele.predict(valeur)
    # predict retourne -1 pour anomalie, 1 pour normal
    return prediction[0] == -1

def score_anomalie(distance_cm: float) -> float:
    """
    Retourne le score d anomalie entre -1 (tres anormal) et 0 (normal).
    Plus le score est negatif, plus c est suspect.
    """
    valeur = np.array([[distance_cm]])
    score = modele.score_samples(valeur)
    return round(float(score[0]), 4)

# ── Tests de validation ────────────────────────────────────
print("\n" + "=" * 55)
print("  Tests de detection d anomalies")
print("=" * 55)

cas_tests = [
    (10,   "Place occupee normale"),
    (18,   "Place occupee normale"),
    (175,  "Place libre normale"),
    (200,  "Place libre normale"),
    (0,    "Capteur mort — distance zero"),
    (75,   "Valeur impossible — zone grise"),
    (350,  "Capteur bloque — hors portee"),
    (999,  "Capteur defaillant — valeur max"),
    (50,   "Valeur suspecte"),
    (120,  "Zone ambigue"),
]

for distance, description in cas_tests:
    anomalie = est_anomalie(distance)
    score    = score_anomalie(distance)
    statut   = "ANOMALIE" if anomalie else "NORMAL  "
    print(f"  {distance:>4} cm  [{statut}]  score={score:>7.4f}  — {description}")

print("=" * 55)
print("\n[ML]  Modèle pret a etre integre dans le serveur LDM.")