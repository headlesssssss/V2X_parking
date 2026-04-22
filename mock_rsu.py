import paho.mqtt.client as mqtt
import json, random, time
from datetime import datetime, timezone

# Configuration
BROKER   = "127.0.0.1"
PORT     = 1883
# On définit 2 zones pour couvrir tes 8 capteurs matériels (IDs 1 à 8)
ZONES    = {
    "A": [1, 2, 3, 4], 
    "B": [5, 6, 7, 8]
}
INTERVAL = 2 # Ralenti à 2 secondes pour mieux lire la console

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def generate_cpm(zone_name, sensor_ids):
    spaces = []
    for sid in sensor_ids:
        occupied = random.random() > 0.5
        dist = random.randint(5, 20) if occupied else random.randint(150, 210)
        spaces.append({
            "space_id":    sid, # ID matériel (1 à 8)
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
        "free_count":  sum(1 for s in spaces if not s["occupied"]),
        "total_count": len(sensor_ids)
    }

def generate_denm(zone_name, sensor_ids, seq):
    space = random.choice(sensor_ids)
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
            "description":    "Sensor timeout - no echo received"
        },
        "location": {"space_id": space, "zone": f"ZONE_{zone_name}"},
        "severity": "WARNING"
    }

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connecté au broker Mosquitto OK")
    else:
        print(f"[MQTT] Erreur connexion : code {rc}")

# CORRECTION PAHO MQTT v2.0
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="MockRSU_PC")
client.on_connect = on_connect
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()

print("=" * 55)
print("  Smart Parking - Mock RSU (simulateur ESP32)")
print("  Appuie sur Ctrl+C pour arreter")
print("=" * 55)

seq = 0
try:
    while True:
        for zone_name, sensor_ids in ZONES.items():
            cpm   = generate_cpm(zone_name, sensor_ids)
            topic = f"parking/zone_{zone_name.lower()}/cpm"
            client.publish(topic, json.dumps(cpm))
            free  = cpm["free_count"]
            print(f"[CPM]  zone_{zone_name.lower()}  ->  {free}/4 places libres")

            if random.random() < 0.10: # 10% de chance de générer une anomalie
                seq  += 1
                denm  = generate_denm(zone_name, sensor_ids, seq)
                topic = f"parking/zone_{zone_name.lower()}/denm"
                client.publish(topic, json.dumps(denm))
                place = denm["location"]["space_id"]
                print(f"[DENM] ALERTE zone_{zone_name.lower()}  ->  anomalie capteur {place}")

        print("-" * 55)
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\n[MockRSU] Arret propre.")
    client.loop_stop()
    client.disconnect()