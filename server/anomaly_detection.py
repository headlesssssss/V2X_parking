import os
import numpy as np
import joblib
from collections import deque
from datetime import datetime, timezone, timedelta

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "isolation_forest.pkl")

modele_if = joblib.load(MODEL_PATH)
print(f"[ML]   Modele charge : {MODEL_PATH}")

historiques = {}

def get_historique(place_id):
    if place_id not in historiques:
        historiques[place_id] = {
            "distances":  deque(maxlen=60),
            "timestamps": deque(maxlen=60),
        }
    return historiques[place_id]

def ajouter_mesure(place_id, distance, timestamp=None):
    h = get_historique(place_id)
    h["distances"].append(distance)
    h["timestamps"].append(timestamp or datetime.now(timezone.utc))

def check_zscore(distance, place_id, seuil=3.0):
    h = get_historique(place_id)
    if len(h["distances"]) < 10:
        return False
    historique = list(h["distances"])
    moyenne = np.mean(historique)
    ecart   = np.std(historique)
    if ecart == 0:
        return True
    z = abs((distance - moyenne) / ecart)
    return z > seuil

def check_isolation_forest(distance, place_id):
    h = get_historique(place_id)
    distances = list(h["distances"])
    f1 = distance
    window = distances[-10:] + [distance]
    f2 = float(np.std(window)) if len(window) > 1 else 0.0
    f3 = abs(distance - distances[-1]) if len(distances) > 0 else 0.0
    prediction = modele_if.predict([[f1, f2, f3]])[0]
    return prediction == -1

def check_business_rules(distance, place_id, frozen_min=10, frozen_seconds=10):
    """
    frozen_min     : nombre de mesures identiques pour confirmer figee
    frozen_seconds : duree minimale pour confirmer figee
    """
    h = get_historique(place_id)
    distances  = list(h["distances"])
    timestamps = list(h["timestamps"])

    # Regle 1 : distance physiquement impossible
    if distance < 0.5 or distance > 10.0:
        return True

    # Regle 2 : oscillation brutale
    if len(distances) >= 2:
        delta = abs(distance - distances[-2])
        if delta > 5.0:
            return True

    # Regle 3 : valeur figee
    if len(distances) >= frozen_min:
        derniers = distances[-frozen_min:]
        if max(derniers) - min(derniers) < 0.05:
            if len(timestamps) >= frozen_min:
                duree = (timestamps[-1] - timestamps[-frozen_min]).total_seconds()
                if duree >= frozen_seconds:
                    return True

    return False

def vote_majoritaire(distance, place_id, frozen_min=10, frozen_seconds=10):
    r1 = check_zscore(distance=distance, place_id=place_id)
    r2 = check_isolation_forest(distance=distance, place_id=place_id)
    r3 = check_business_rules(distance=distance, place_id=place_id,
                               frozen_min=frozen_min, frozen_seconds=frozen_seconds)
    votes = sum([r1, r2, r3])
    return {
        "anomalie":         votes >= 2,
        "votes":            votes,
        "zscore":           r1,
        "isolation_forest": r2,
        "business_rules":   r3,
    }

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Tests unitaires — Detection d anomalies")
    print("=" * 60)

    def simuler(place_id, distances, desc, attendu,
                timestamps=None, frozen_min=10, frozen_seconds=10):
        for i, d in enumerate(distances):
            ts = timestamps[i] if timestamps else None
            ajouter_mesure(place_id, d, ts)
        d_test = distances[-1]
        result = vote_majoritaire(d_test, place_id,
                                  frozen_min=frozen_min,
                                  frozen_seconds=frozen_seconds)
        statut = "ANOMALIE" if result["anomalie"] else "NORMAL  "
        ok = "OK   " if (result["anomalie"] == attendu) else "ECHEC"
        print(f"\n  [{statut}] [{ok}] {desc}")
        print(f"    dist={d_test}cm  votes={result['votes']}/3"
              f"  zscore={result['zscore']}"
              f"  IF={result['isolation_forest']}"
              f"  rules={result['business_rules']}")

    print("\n── CAS NORMAUX (attendu : NORMAL) ────────────────────")

    simuler("A1",
        [2.1,2.0,2.2,1.9,2.1,2.0,2.1,2.2,2.0,2.1,2.0],
        "Place occupee stable", attendu=False)

    simuler("A2",
        [7.0,7.1,6.9,7.0,7.2,6.8,7.1,7.0,6.9,7.1,7.0],
        "Place libre stable", attendu=False)

    simuler("A3",
        [2.0,6.8,7.0,7.1,6.9,7.0,7.2,6.8,7.0,6.9,7.1],
        "Voiture qui part — transition normale", attendu=False)

    print("\n── CAS ANOMALIES (attendu : ANOMALIE) ────────────────")

    simuler("B1",
        [2.0,2.1,2.0,1.9,2.1,2.0,2.2,2.0,2.1,2.0,0.2],
        "Capteur mort (0.2 cm)", attendu=True)

    simuler("B2",
        [7.0,7.1,6.9,7.0,7.2,6.8,7.0,7.1,6.9,7.0,13.5],
        "Hors portee (13.5 cm)", attendu=True)

    # Cas figee : timestamps etalés sur 15 secondes
    t0 = datetime.now(timezone.utc)
    ts_figes = [t0 + timedelta(seconds=i*1.5) for i in range(11)]
    simuler("B3",
        [4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5,4.5],
        "Valeur completement figee (4.5 cm)",
        attendu=True,
        timestamps=ts_figes,
        frozen_min=10,
        frozen_seconds=10)

    # Cas oscillation : historique stable puis saut brutal
    simuler("B4",
        [2.0,2.0,2.1,2.0,1.9,2.0,2.1,2.0,1.9,2.0,7.5],
        "Oscillation brutale occupee->libre (2cm -> 7.5cm)", attendu=True)

    print("\n" + "=" * 60)
    print("[OK]  Tests termines !")