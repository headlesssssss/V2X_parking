import paho.mqtt.client as mqtt
import json, random, time
from datetime import datetime, timezone

# Configuration
BROKER   = "localhost"
PORT     = 1883
ZONES    = ["A", "B", "C", "D"]
INTERVAL = 0.5

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def generate_cpm(zone):
    spaces = []
    for i in range(1, 5):
        occupied = random.random() > 0.5
        dist = random.randint(5, 20) if occupied else random.randint(150, 210)
        spaces.append({
            "space_id":    f"{zone}{i}",
            "occupied":    occupied,
            "distance_cm": dist,
            "confidence":  round(random.uniform(0.93, 0.99), 2)
        })
    return {
        "header": {
            "protocol_version": 1,
            "message_type":     "CPM",
            "station_id":       f"RSU_ZONE_{zone}",
            "timestamp":        now_iso()
        },
        "parking_spaces": spaces,
        "free_count":  sum(1 for s in spaces if not s["occupied"]),
        "total_count": 4
    }

def generate_denm(zone, seq):
    space = f"{zone}{random.randint(1, 4)}"
    return {
        "header": {
            "protocol_version": 1,
            "message_type":     "DENM",
            "station_id":       f"RSU_ZONE_{zone}",
            "timestamp":        now_iso(),
            "sequence_number":  seq
        },
        "management": {
            "action_id":         f"RSU_ZONE_{zone}_{seq}",
            "detection_time":    now_iso(),
            "validity_duration": 30
        },
        "situation": {
            "cause_code":     91,
            "sub_cause_code": 1,
            "description":    "Sensor timeout — no echo received"
        },
        "location": {"space_id": space, "zone": f"ZONE_{zone}"},
        "severity": "WARNING"
    }

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT]  Connecte au broker Mosquitto OK")
    else:
        print(f"[MQTT]  Erreur connexion : code {rc}")

client = mqtt.Client(client_id="MockRSU_PC")
client.on_connect = on_connect
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()

print("=" * 55)
print("  Smart Parking — Mock RSU (simulateur ESP32)")
print("  Appuie sur Ctrl+C pour arreter")
print("=" * 55)

seq = 0
try:
    while True:
        for zone in ZONES:
            cpm   = generate_cpm(zone)
            topic = f"parking/zone_{zone.lower()}/cpm"
            client.publish(topic, json.dumps(cpm))
            free  = cpm["free_count"]
            print(f"[CPM]   zone_{zone.lower()}  ->  {free}/4 places libres")

            if random.random() < 0.10:
                seq  += 1
                denm  = generate_denm(zone, seq)
                topic = f"parking/zone_{zone.lower()}/denm"
                client.publish(topic, json.dumps(denm))
                place = denm["location"]["space_id"]
                print(f"[DENM]  ALERTE zone_{zone.lower()}  ->  anomalie place {place}")

        print("-" * 55)
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\n[MockRSU] Arret propre.")
    client.loop_stop()
    client.disconnect()
