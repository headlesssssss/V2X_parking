import paho.mqtt.client as mqtt
import json, random, time, csv, os
from datetime import datetime, timezone

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────
BROKER   = "127.0.0.1"
PORT     = 1883
ZONES    = {
    "A": [1, 2, 3, 4],
    "B": [5, 6, 7, 8]
}
INTERVAL      = 2          # secondes entre chaque cycle
CSV_FILE      = "dataset_parking.csv"
TARGET_ROWS   = 5000       # arrêt automatique quand atteint (0 = infini)
ANOMALY_PROBA = 0.08       # probabilité de déclenchement d'une anomalie sur une place normale

# ─────────────────────────────────────────────
#  CONSTANTES DE DISTANCE — MAQUETTE (place 8 × 6.5 cm)
#  Le capteur est positionné en bout de place (axe 8 cm).
#
#    "free"      → capteur voit le fond de la place     : 6.0 – 8.0 cm  ± 0.2 cm
#    "occupied"  → mini-voiture devant le capteur       : 1.5 – 3.0 cm  ± 0.1 cm
#    "transition"→ voiture qui entre, dist. décroissante: pas 0.5 – 1.2 cm/cycle
#    "anomaly_1" → hors plage physique de la maquette   : < 1.0 cm  ou  > 10.0 cm
#    "anomaly_2" → oscillation libre ↔ occupé           : 1.5 cm  ↔  7.5 cm
#    "anomaly_3" → valeur figée entre 2.0 – 7.0 cm      : ~150-200 cycles (~5 min)
#
#  Seuil CPM occupé/libre : 4.0 cm
# ─────────────────────────────────────────────

DIST_FREE_MIN        = 6.0    # cm — distance minimale place libre
DIST_FREE_MAX        = 8.0    # cm — distance maximale place libre
DIST_FREE_NOISE      = 0.2    # cm — bruit réaliste état libre

DIST_OCC_MIN         = 1.5    # cm — distance minimale place occupée
DIST_OCC_MAX         = 3.0    # cm — distance maximale place occupée
DIST_OCC_NOISE       = 0.1    # cm — bruit réaliste état occupé

DIST_TRANS_STEP_MIN  = 0.5    # cm — décrement min par cycle (transition)
DIST_TRANS_STEP_MAX  = 1.2    # cm — décrement max par cycle (transition)
DIST_TRANS_MARGIN    = 0.3    # cm — marge pour valider fin de transition

DIST_ANOM1_LOW_MAX   = 0.9    # cm — seuil haut anomalie "trop proche"
DIST_ANOM1_HIGH_MIN  = 10.1   # cm — seuil bas  anomalie "trop loin"
DIST_ANOM1_HIGH_MAX  = 15.0   # cm — seuil haut anomalie "trop loin"

DIST_ANOM2_OCC       = 1.5    # cm — valeur basse oscillation (simule occupé)
DIST_ANOM2_FREE      = 7.5    # cm — valeur haute oscillation (simule libre)

DIST_ANOM3_MIN       = 2.0    # cm — valeur figée minimale
DIST_ANOM3_MAX       = 7.0    # cm — valeur figée maximale

DIST_OCCUPIED_THRESHOLD = 4.0 # cm — seuil CPM : dist < 4 cm → occupé


# ─────────────────────────────────────────────
#  MACHINE D'ÉTAT PAR PLACE
# ─────────────────────────────────────────────

place_states = {}

def init_place(place_id):
    """Initialise une place avec un état aléatoire libre ou occupé."""
    state = random.choice(["free", "occupied"])
    place_states[place_id] = {
        "state":              state,
        "base_distance":      round(random.uniform(DIST_FREE_MIN, DIST_FREE_MAX), 2)
                              if state == "free"
                              else round(random.uniform(DIST_OCC_MIN, DIST_OCC_MAX), 2),
        "transition_dist":    None,
        "frozen_value":       None,
        "frozen_counter":     0,
        "oscillation_toggle": False,
        "state_counter":      0,
    }


def get_distance(place_id):
    """
    Retourne (distance_cm, est_anomalie) selon l'état actuel de la place.
    Toutes les distances sont en cm, adaptées à la maquette.
    """
    s = place_states[place_id]
    state = s["state"]
    est_anomalie = 0

    # ── ÉTAT : LIBRE ──────────────────────────────────────────────────────────
    if state == "free":
        dist = s["base_distance"] + random.uniform(-DIST_FREE_NOISE, DIST_FREE_NOISE)
        dist = round(max(0.1, dist), 2)

        s["state_counter"] += 1
        if s["state_counter"] > random.randint(20, 60) and random.random() < 0.15:
            s["state"] = "transition"
            s["transition_dist"] = s["base_distance"]
            s["state_counter"] = 0

    # ── ÉTAT : OCCUPÉ ─────────────────────────────────────────────────────────
    elif state == "occupied":
        dist = s["base_distance"] + random.uniform(-DIST_OCC_NOISE, DIST_OCC_NOISE)
        dist = round(max(0.1, dist), 2)

        s["state_counter"] += 1
        if s["state_counter"] > random.randint(30, 80) and random.random() < 0.12:
            s["state"] = "free"
            s["base_distance"] = round(random.uniform(DIST_FREE_MIN, DIST_FREE_MAX), 2)
            s["state_counter"] = 0

    # ── ÉTAT : TRANSITION (libre → occupé) ───────────────────────────────────
    elif state == "transition":
        target = round(random.uniform(DIST_OCC_MIN, DIST_OCC_MAX), 2)
        s["transition_dist"] -= random.uniform(DIST_TRANS_STEP_MIN, DIST_TRANS_STEP_MAX)
        dist = round(max(target, s["transition_dist"]), 2)

        if dist <= target + DIST_TRANS_MARGIN:
            s["state"] = "occupied"
            s["base_distance"] = round(dist, 2)
            s["state_counter"] = 0

    # ── ANOMALIE TYPE 1 : valeur hors plage physique ──────────────────────────
    elif state == "anomaly_1":
        if random.random() < 0.5:
            dist = round(random.uniform(0.1, DIST_ANOM1_LOW_MAX), 2)   # trop proche (< 1 cm)
        else:
            dist = round(random.uniform(DIST_ANOM1_HIGH_MIN, DIST_ANOM1_HIGH_MAX), 2)  # trop loin (> 10 cm)
        est_anomalie = 1

        s["state_counter"] += 1
        if s["state_counter"] > random.randint(5, 15):
            _reset_to_normal(place_id)

    # ── ANOMALIE TYPE 2 : oscillation rapide libre ↔ occupé ───────────────────
    elif state == "anomaly_2":
        s["oscillation_toggle"] = not s["oscillation_toggle"]
        dist = DIST_ANOM2_OCC if s["oscillation_toggle"] else DIST_ANOM2_FREE
        est_anomalie = 1

        s["state_counter"] += 1
        if s["state_counter"] > random.randint(10, 25):
            _reset_to_normal(place_id)

    # ── ANOMALIE TYPE 3 : valeur figée ────────────────────────────────────────
    elif state == "anomaly_3":
        if s["frozen_value"] is None:
            s["frozen_value"] = round(random.uniform(DIST_ANOM3_MIN, DIST_ANOM3_MAX), 2)
        dist = s["frozen_value"]                          # EXACTEMENT la même valeur
        s["frozen_counter"] += 1
        est_anomalie = 1 if s["frozen_counter"] > 30 else 0  # confirmée après 30 cycles (~1 min)

        if s["frozen_counter"] > random.randint(150, 200):   # ~5 min
            _reset_to_normal(place_id)

    else:
        dist = 0.0

    return round(dist, 2), est_anomalie


def _reset_to_normal(place_id):
    """Remet une place en état normal (libre ou occupé) après une anomalie."""
    s = place_states[place_id]
    new_state = random.choice(["free", "occupied"])
    s["state"]            = new_state
    s["base_distance"]    = round(random.uniform(DIST_FREE_MIN, DIST_FREE_MAX), 2) \
                            if new_state == "free" \
                            else round(random.uniform(DIST_OCC_MIN, DIST_OCC_MAX), 2)
    s["frozen_value"]     = None
    s["frozen_counter"]   = 0
    s["state_counter"]    = 0


def maybe_trigger_anomaly(place_id):
    """
    Avec une faible probabilité, bascule une place normale
    vers l'un des 3 types d'anomalies.
    """
    s = place_states[place_id]
    if s["state"] in ("free", "occupied") and random.random() < ANOMALY_PROBA:
        anomaly = random.choice(["anomaly_1", "anomaly_2", "anomaly_3"])
        s["state"]              = anomaly
        s["state_counter"]      = 0
        s["frozen_value"]       = None
        s["frozen_counter"]     = 0
        s["oscillation_toggle"] = False


# ─────────────────────────────────────────────
#  FORMATAGE DES MESSAGES MQTT (CPM / DENM)
# ─────────────────────────────────────────────

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def generate_cpm(zone_name, sensor_ids, readings):
    """readings : liste de (place_id, distance_cm, est_anomalie, occupied)"""
    spaces = []
    for place_id, dist, est_anom, occupied in readings:
        spaces.append({
            "space_id":    place_id,
            "occupied":    occupied,
            "distance_cm": dist,
            "confidence":  round(random.uniform(0.93, 0.99), 2)
        })
    return {
        "header": {
            "protocol_version": 1,
            "message_type":     "CPM",
            "station_id":       f"RSU_ZONE_{zone_name}",
            "timestamp":        now_iso()
        },
        "parking_spaces": spaces,
        "free_count":  sum(1 for _, _, _, occ in readings if not occ),
        "total_count": len(sensor_ids)
    }

def generate_denm(zone_name, place_id, seq):
    return {
        "header": {
            "protocol_version": 1,
            "message_type":     "DENM",
            "station_id":       f"RSU_ZONE_{zone_name}",
            "timestamp":        now_iso(),
            "sequence_number":  seq
        },
        "management": {
            "action_id":         f"RSU_ZONE_{zone_name}_{seq}",
            "detection_time":    now_iso(),
            "validity_duration": 30
        },
        "situation": {
            "cause_code":     91,
            "sub_cause_code": 1,
            "description":    "Sensor anomaly detected"
        },
        "location": {"space_id": place_id, "zone": f"ZONE_{zone_name}"},
        "severity": "WARNING"
    }


# ─────────────────────────────────────────────
#  MQTT
# ─────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connecté au broker Mosquitto OK")
    else:
        print(f"[MQTT] Erreur connexion : code {rc}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="MockRSU_PC")
client.on_connect = on_connect
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()


# ─────────────────────────────────────────────
#  INITIALISATION DES PLACES ET DU CSV
# ─────────────────────────────────────────────

all_ids = [sid for ids in ZONES.values() for sid in ids]
for pid in all_ids:
    init_place(pid)

csv_exists = os.path.exists(CSV_FILE)
csv_file   = open(CSV_FILE, "a", newline="", encoding="utf-8")
csv_writer = csv.writer(csv_file)
if not csv_exists:
    csv_writer.writerow(["timestamp", "place_id", "distance_cm", "est_anomalie"])
    csv_file.flush()

print("=" * 60)
print("  Smart Parking - Mock RSU  [MAQUETTE 8×6.5 cm]")
print(f"  Libre : {DIST_FREE_MIN}–{DIST_FREE_MAX} cm  |  Occupé : {DIST_OCC_MIN}–{DIST_OCC_MAX} cm")
print(f"  Export CSV : {CSV_FILE}")
print(f"  Objectif   : {TARGET_ROWS} lignes  |  Ctrl+C pour arrêter")
print("=" * 60)

seq        = 0
row_count  = 0
start_time = time.time()

# ─────────────────────────────────────────────
#  BOUCLE PRINCIPALE
# ─────────────────────────────────────────────
try:
    while True:
        ts = now_iso()

        for zone_name, sensor_ids in ZONES.items():
            readings = []

            for place_id in sensor_ids:
                maybe_trigger_anomaly(place_id)
                dist, est_anom = get_distance(place_id)

                # Seuil adapté à la maquette : < 4.0 cm → occupé
                occupied = dist < DIST_OCCUPIED_THRESHOLD and est_anom == 0

                readings.append((place_id, dist, est_anom, occupied))

                csv_writer.writerow([ts, place_id, dist, est_anom])
                row_count += 1

            csv_file.flush()

            # ── Publication MQTT CPM ──────────────────────────────────────
            cpm   = generate_cpm(zone_name, sensor_ids, readings)
            topic = f"parking/zone_{zone_name.lower()}/cpm"
            client.publish(topic, json.dumps(cpm))
            free  = cpm["free_count"]

            state_summary = " ".join(
                f"P{pid}={'ANO' if anom else ('OCC' if occ else 'LIB')}({dist}cm)"
                for pid, dist, anom, occ in readings
            )
            print(f"[CPM]  zone_{zone_name.lower()}  {free}/4 libres  |  {state_summary}")

            # ── Publication MQTT DENM si anomalie ─────────────────────────
            for place_id, dist, est_anom, occ in readings:
                if est_anom == 1:
                    seq  += 1
                    denm  = generate_denm(zone_name, place_id, seq)
                    topic = f"parking/zone_{zone_name.lower()}/denm"
                    client.publish(topic, json.dumps(denm))
                    print(f"[DENM] ALERTE zone_{zone_name.lower()}  ->  anomalie capteur {place_id}  dist={dist}cm")

        elapsed = time.time() - start_time
        eta_sec = (TARGET_ROWS - row_count) * INTERVAL / len(all_ids) if row_count < TARGET_ROWS else 0
        print(f"       CSV : {row_count} lignes  |  {elapsed/60:.1f} min écoulées  |  ETA : {eta_sec/60:.1f} min")
        print("-" * 60)

        if TARGET_ROWS > 0 and row_count >= TARGET_ROWS:
            print(f"\n[MockRSU] Objectif {TARGET_ROWS} lignes atteint. Arrêt automatique.")
            break

        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print(f"\n[MockRSU] Arrêt manuel. {row_count} lignes sauvegardées dans '{CSV_FILE}'.")

finally:
    csv_file.close()
    client.loop_stop()
    client.disconnect()
    print(f"[MockRSU] Fichier CSV fermé proprement.")
