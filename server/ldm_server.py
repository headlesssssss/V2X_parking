import paho.mqtt.client as mqtt
import json
from datetime import datetime

# ── Configuration ──────────────────────────────────────────
BROKER = "localhost"
PORT   = 1883
ZONES  = ["A", "B", "C", "D"]

# ── LDM — Local Dynamic Map ────────────────────────────────
# Structure en memoire representant les 16 places du parking
ldm = {}
for zone in ZONES:
    for i in range(1, 5):
        place_id = f"{zone}{i}"
        ldm[place_id] = {
            "space_id":    place_id,
            "zone":        zone,
            "occupied":    False,
            "distance_cm": 0,
            "confidence":  0.0,
            "last_update": None,
            "anomaly":     False
        }

def afficher_ldm():
    """Affiche l etat complet du parking dans le terminal."""
    print("\n" + "=" * 60)
    print("  LDM — Local Dynamic Map — Smart Parking")
    print("=" * 60)
    total_libres = 0
    for zone in ZONES:
        libres = 0
        print(f"\n  Zone {zone} :")
        for i in range(1, 5):
            place_id = f"{zone}{i}"
            p = ldm[place_id]
            etat = "OCCUPEE" if p["occupied"] else "LIBRE  "
            anomalie = " [ANOMALIE]" if p["anomaly"] else ""
            dist = f"{p['distance_cm']:>4} cm" if p["distance_cm"] else "  -- cm"
            print(f"    {place_id} : {etat}  {dist}  conf={p['confidence']:.2f}{anomalie}")
            if not p["occupied"]:
                libres += 1
        total_libres += libres
        print(f"    --> {libres}/4 places libres")
    print(f"\n  TOTAL : {total_libres}/16 places libres")
    print("=" * 60)

# ── Callbacks MQTT ─────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT]  Connecte au broker Mosquitto OK")
        # S abonner a tous les topics du parking
        client.subscribe("parking/#")
        print("[MQTT]  Abonne a parking/#")
    else:
        print(f"[MQTT]  Erreur connexion : code {rc}")

def on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode("utf-8")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        print(f"[ERREUR] JSON invalide sur {topic}")
        return

    message_type = data.get("header", {}).get("message_type", "")

    # ── Traitement CPM ──────────────────────────────────────
    if message_type == "CPM":
        station_id = data["header"]["station_id"]
        timestamp  = data["header"]["timestamp"]
        spaces     = data.get("parking_spaces", [])

        for space in spaces:
            place_id = space["space_id"]
            if place_id in ldm:
                # Mise a jour de la LDM
                ldm[place_id]["occupied"]    = space["occupied"]
                ldm[place_id]["distance_cm"] = space["distance_cm"]
                ldm[place_id]["confidence"]  = space["confidence"]
                ldm[place_id]["last_update"] = timestamp
                ldm[place_id]["anomaly"]     = False

        free = data.get("free_count", 0)
        print(f"[CPM]   {station_id}  ->  {free}/4 libres")
        afficher_ldm()

    # ── Traitement DENM ─────────────────────────────────────
    elif message_type == "DENM":
        station_id = data["header"]["station_id"]
        place_id   = data["location"]["space_id"]
        severity   = data["severity"]
        cause      = data["situation"]["description"]

        # Marquer la place comme anomalie dans la LDM
        if place_id in ldm:
            ldm[place_id]["anomaly"] = True

        print(f"[DENM]  ALERTE {station_id} -> place {place_id} | {severity} | {cause}")

    else:
        print(f"[INFO]  Message inconnu sur {topic}")

# ── Lancement ──────────────────────────────────────────────
client = mqtt.Client(client_id="LDM_Server")
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)

print("=" * 60)
print("  Smart Parking — Serveur LDM")
print("  Appuie sur Ctrl+C pour arreter")
print("=" * 60)

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[LDM] Arret propre.")
    client.disconnect()