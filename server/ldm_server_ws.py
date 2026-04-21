import paho.mqtt.client as mqtt
import asyncio
import websockets
import json
import threading
import numpy as np
from sklearn.ensemble import IsolationForest
from datetime import datetime

# ── Configuration ──────────────────────────────────────────
BROKER      = "localhost"
MQTT_PORT   = 1883
WS_PORT     = 8765
ZONES       = ["A", "B", "C", "D"]

# ── LDM — Local Dynamic Map ────────────────────────────────
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

# ── Clients WebSocket connectes ────────────────────────────
ws_clients = set()

# ── Isolation Forest ───────────────────────────────────────
print("[ML]   Entraînement Isolation Forest...")
np.random.seed(42)
occupees = np.random.uniform(5, 25, 1000)
libres   = np.random.uniform(150, 210, 1000)
donnees  = np.concatenate([occupees, libres]).reshape(-1, 1)
modele   = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
modele.fit(donnees)
print("[ML]   Modele pret !")

def est_anomalie(distance_cm: float) -> bool:
    valeur = np.array([[distance_cm]])
    return modele.predict(valeur)[0] == -1

# ── Envoi LDM vers tous les clients WebSocket ──────────────
def envoyer_ldm():
    """Envoie l etat complet de la LDM a tous les clients connectes."""
    if not ws_clients:
        return
    message = json.dumps({
        "type":      "LDM_UPDATE",
        "timestamp": datetime.utcnow().isoformat(),
        "places":    list(ldm.values()),
        "stats": {
            "total":  16,
            "libres": sum(1 for p in ldm.values() if not p["occupied"] and not p["anomaly"]),
            "occupees": sum(1 for p in ldm.values() if p["occupied"]),
            "anomalies": sum(1 for p in ldm.values() if p["anomaly"])
        }
    })
    # Envoyer a tous les clients connectes
    asyncio.run(diffuser(message))

async def diffuser(message: str):
    """Diffuse un message a tous les clients WebSocket."""
    if ws_clients:
        disconnected = set()
        for client in ws_clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        ws_clients.difference_update(disconnected)

# ── Affichage terminal ─────────────────────────────────────
def afficher_ldm():
    libres    = sum(1 for p in ldm.values() if not p["occupied"] and not p["anomaly"])
    occupees  = sum(1 for p in ldm.values() if p["occupied"])
    anomalies = sum(1 for p in ldm.values() if p["anomaly"])
    print(f"\n[LDM]  Total: {libres}/16 libres | {occupees} occupees | {anomalies} anomalies")

# ── Callbacks MQTT ─────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT]  Connecte au broker OK")
        client.subscribe("parking/#")
        print("[MQTT]  Abonne a parking/#")
    else:
        print(f"[MQTT]  Erreur : code {rc}")

def on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode("utf-8")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return

    message_type = data.get("header", {}).get("message_type", "")

    # ── Traitement CPM ──────────────────────────────────────
    if message_type == "CPM":
        spaces = data.get("parking_spaces", [])
        for space in spaces:
            place_id = space["space_id"]
            if place_id in ldm:
                distance = space["distance_cm"]
                anomalie = est_anomalie(distance)
                ldm[place_id]["occupied"]    = space["occupied"]
                ldm[place_id]["distance_cm"] = distance
                ldm[place_id]["confidence"]  = space["confidence"]
                ldm[place_id]["last_update"] = data["header"]["timestamp"]
                ldm[place_id]["anomaly"]     = anomalie
                if anomalie:
                    print(f"[ML]   ANOMALIE detectee sur {place_id} : {distance} cm")

        afficher_ldm()
        envoyer_ldm()

    # ── Traitement DENM ─────────────────────────────────────
    elif message_type == "DENM":
        place_id = data["location"]["space_id"]
        severity = data["severity"]
        if place_id in ldm:
            ldm[place_id]["anomaly"] = True
        print(f"[DENM]  ALERTE place {place_id} | {severity}")
        envoyer_ldm()

# ── Serveur WebSocket ──────────────────────────────────────
async def ws_handler(websocket, path):
    """Gere la connexion d un nouveau client WebSocket."""
    ws_clients.add(websocket)
    client_ip = websocket.remote_address[0]
    print(f"[WS]   Nouveau client connecte : {client_ip}")

    # Envoyer la LDM immediatement a la connexion
    message = json.dumps({
        "type":   "LDM_UPDATE",
        "timestamp": datetime.utcnow().isoformat(),
        "places": list(ldm.values()),
        "stats": {
            "total":     16,
            "libres":    sum(1 for p in ldm.values() if not p["occupied"]),
            "occupees":  sum(1 for p in ldm.values() if p["occupied"]),
            "anomalies": sum(1 for p in ldm.values() if p["anomaly"])
        }
    })
    await websocket.send(message)

    try:
        await websocket.wait_closed()
    finally:
        ws_clients.discard(websocket)
        print(f"[WS]   Client deconnecte : {client_ip}")

async def lancer_ws():
    """Lance le serveur WebSocket."""
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        print(f"[WS]   Serveur WebSocket demarre sur ws://localhost:{WS_PORT}")
        await asyncio.Future()

def thread_ws():
    """Lance le WebSocket dans un thread separe."""
    asyncio.run(lancer_ws())

# ── Lancement principal ────────────────────────────────────
print("=" * 60)
print("  Smart Parking — Serveur ITS Edge complet")
print("  MQTT + LDM + Isolation Forest + WebSocket")
print("  Ctrl+C pour arreter")
print("=" * 60)

# Lancer le WebSocket dans un thread separe
ws_thread = threading.Thread(target=thread_ws, daemon=True)
ws_thread.start()

# Lancer le client MQTT
mqtt_client = mqtt.Client(client_id="LDM_Server_WS")
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(BROKER, MQTT_PORT, keepalive=60)

try:
    mqtt_client.loop_forever()
except KeyboardInterrupt:
    print("\n[Serveur] Arret propre.")
    mqtt_client.disconnect()