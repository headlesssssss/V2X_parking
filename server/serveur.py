import os
import sys
import json
import sqlite3
import threading
import heapq
import time
from datetime import datetime, timezone

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anomaly_detection import ajouter_mesure, vote_majoritaire

# ── Config ───────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, "conf_parking.json")) as f:
    CONF = json.load(f)

GRID      = CONF["grid"]
ENTRY     = (CONF["entry"]["row"], CONF["entry"]["col"])
THRESHOLD = float(CONF["threshold_cm"])
# hw_id (str) → spot_id (int)
SENSORS   = {str(k): int(v) for k, v in CONF["spots_mapping"].items()}
# spot_id (int) → hw_id (str)
SPOT_TO_HW = {v: k for k, v in SENSORS.items()}

SPOT_COORDS: dict[int, tuple[int, int]] = {}
for _r, _row in enumerate(GRID):
    for _c, _val in enumerate(_row):
        if isinstance(_val, int) and 10 <= _val <= 90:
            SPOT_COORDS[_val] = (_r, _c)

# ── State ────────────────────────────────────────────────────────────────────
etat: dict[int, str] = {sid: "FREE" for sid in SPOT_COORDS}
state_lock = threading.Lock()

# ── SQLite ───────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(BASE, "parking.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mesures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_id     INTEGER,
                hardware_id TEXT,
                distance_cm REAL,
                etat        TEXT,
                anomalie    INTEGER,
                zscore      INTEGER,
                if_flag     INTEGER,
                rules_flag  INTEGER,
                ts          TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS denm_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                hardware_id TEXT,
                spot_id     INTEGER,
                reason      TEXT,
                ts          TEXT
            )
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_insert_mesure(spot_id, hw_id, dist, etat_val, res) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO mesures VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (spot_id, hw_id, dist, etat_val,
             int(res["anomalie"]), int(res["zscore"]),
             int(res["isolation_forest"]), int(res["business_rules"]), _now()),
        )


def db_insert_denm(hw_id, spot_id, reason) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO denm_alerts VALUES (NULL,?,?,?,?)",
            (hw_id, spot_id, reason, _now()),
        )


# ── A* ───────────────────────────────────────────────────────────────────────
def astar(start: tuple, target_spot: int) -> list[list[int]]:
    """Retourne le chemin [[row,col], ...] de start jusqu'au spot cible, ou []."""
    goal = SPOT_COORDS[target_spot]
    rows, cols = len(GRID), len(GRID[0])

    def h(pos):
        return abs(pos[0] - goal[0]) + abs(pos[1] - goal[1])

    def passable(r, c):
        v = GRID[r][c]
        if v in (1, 99):
            return False
        if 10 <= v <= 90:
            return (r, c) == goal   # seul le goal spot est traversable
        return True                  # 0 ou 98

    heap = [(h(start), 0, start)]
    came: dict = {}
    cost: dict = {start: 0}

    while heap:
        _, g, cur = heapq.heappop(heap)
        if cur == goal:
            path = []
            while cur in came:
                path.append(list(cur))
                cur = came[cur]
            path.append(list(start))
            return list(reversed(path))
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nb = (cur[0] + dr, cur[1] + dc)
            if 0 <= nb[0] < rows and 0 <= nb[1] < cols and passable(*nb):
                ng = g + 1
                if ng < cost.get(nb, 10 ** 9):
                    cost[nb] = ng
                    came[nb] = cur
                    heapq.heappush(heap, (ng + h(nb), ng, nb))
    return []


def nearest_free() -> tuple[int | None, list]:
    with state_lock:
        free = [s for s, st in etat.items() if st == "FREE"]
    best_spot, best_path = None, None
    for sid in free:
        p = astar(ENTRY, sid)
        if p and (best_path is None or len(p) < len(best_path)):
            best_spot, best_path = sid, p
    return best_spot, best_path or []


# ── Flask / SocketIO ─────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "v2x-parking-2024"
sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/qr")
def qr_page():
    """Page affichant le QR code pour accéder à la PWA."""
    import socket as sock
    # Trouver l'IP locale du PC
    try:
        s = sock.socket(sock.AF_INET, sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    url = f"http://{local_ip}:5000"
    return render_template("qr.html", url=url, ip=local_ip)


@app.route("/3d")
def view_3d():
    """Vue 3D interactive du parking."""
    return render_template("parking3d.html")


@app.route("/api/mapem")
def api_mapem():
    with state_lock:
        spots = {
            str(sid): {
                "row": rc[0],
                "col": rc[1],
                "hardware_id": SPOT_TO_HW.get(sid),
                "etat": etat[sid],
            }
            for sid, rc in SPOT_COORDS.items()
        }
    return jsonify({
        "zone_name":    CONF["zone_name"],
        "grid":         GRID,
        "entry":        CONF["entry"],
        "threshold_cm": THRESHOLD,
        "spots":        spots,
    })


@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify({str(k): v for k, v in etat.items()})


@app.route("/api/guidance", methods=["POST"])
def api_guidance():
    data = request.get_json(silent=True) or {}
    spot_id = data.get("spot_id")

    if spot_id is not None:
        sid = int(spot_id)
        if sid not in SPOT_COORDS:
            return jsonify({"error": "spot inconnu"}), 400
        path = astar(ENTRY, sid)
        return jsonify({"spot_id": sid, "path": path})

    sid, path = nearest_free()
    if sid is None:
        return jsonify({"error": "parking complet"}), 503
    return jsonify({"spot_id": sid, "path": path})


@app.route("/api/history")
def api_history():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT spot_id,hardware_id,distance_cm,etat,anomalie,ts "
            "FROM mesures ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return jsonify([
        {"spot_id": r[0], "hardware_id": r[1], "distance_cm": r[2],
         "etat": r[3], "anomalie": bool(r[4]), "ts": r[5]}
        for r in rows
    ])


@app.route("/api/denm")
def api_denm():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT hardware_id,spot_id,reason,ts "
            "FROM denm_alerts ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return jsonify([
        {"hardware_id": r[0], "spot_id": r[1], "reason": r[2], "ts": r[3]}
        for r in rows
    ])


# ── MQTT Processing ──────────────────────────────────────────────────────────
def _snapshot() -> dict:
    with state_lock:
        return {str(k): v for k, v in etat.items()}


def handle_cpm(hw_id: str, payload: dict) -> None:
    dist = payload.get("distance_cm")
    if dist is None:
        return
    dist = float(dist)

    sid = SENSORS.get(hw_id)
    if sid is None:
        return

    ajouter_mesure(sid, dist)
    res = vote_majoritaire(dist, sid)

    if res["anomalie"]:
        new_etat = "ANOMALY"
        db_insert_denm(hw_id, sid, (
            f"Vote {res['votes']}/3 — "
            f"Z-score:{'oui' if res['zscore'] else 'non'} | "
            f"IF:{'oui' if res['isolation_forest'] else 'non'} | "
            f"Regles:{'oui' if res['business_rules'] else 'non'}"
        ))
    elif dist < THRESHOLD:
        new_etat = "OCCUPIED"
    else:
        new_etat = "FREE"

    with state_lock:
        etat[sid] = new_etat

    snap = _snapshot()
    free  = sum(1 for v in snap.values() if v == "FREE")
    occ   = sum(1 for v in snap.values() if v == "OCCUPIED")
    anom  = sum(1 for v in snap.values() if v == "ANOMALY")

    db_insert_mesure(sid, hw_id, dist, new_etat, res)

    sio.emit("spatem", {
        "spot_id":      sid,
        "hw_id":        hw_id,
        "distance_cm":  dist,
        "etat":         new_etat,
        "anomalie":     res,
        "snapshot":     snap,
        "free":         free,
        "occupied":     occ,
        "anomaly_count": anom,
        "ts":           _now(),
    })

    # Envoyer le guidage A* automatiquement à chaque changement
    best_spot, best_path = nearest_free()
    sio.emit("guidance_update", {
        "spot_id": best_spot,
        "path":    best_path,
        "free":    free,
    })

    if new_etat == "ANOMALY":
        sio.emit("denm", {
            "hw_id":   hw_id,
            "spot_id": sid,
            "reason":  (
                f"Anomalie detectee — dist={dist:.1f}cm, "
                f"votes={res['votes']}/3"
            ),
            "ts": _now(),
        })


def handle_denm(hw_id: str, payload: dict) -> None:
    sid    = SENSORS.get(hw_id)
    reason = payload.get("reason", "DENM recu de l ESP32")
    db_insert_denm(hw_id, sid, reason)
    sio.emit("denm", {
        "hw_id":   hw_id,
        "spot_id": sid,
        "reason":  reason,
        "ts":      _now(),
    })


def on_connect(client, userdata, flags, rc, *args):
    print(f"[MQTT] Connecte au broker (rc={rc})")
    client.subscribe([("parking/+/cpm", 0), ("parking/+/denm", 0)])


def on_message(client, userdata, msg):
    try:
        parts    = msg.topic.split("/")   # parking / hw_id / cpm|denm
        hw_id    = parts[1]
        kind     = parts[2]
        payload  = json.loads(msg.payload.decode())
        if kind == "cpm":
            handle_cpm(hw_id, payload)
        elif kind == "denm":
            handle_denm(hw_id, payload)
    except Exception as exc:
        print(f"[MQTT] Erreur traitement: {exc}")


def mqtt_thread() -> None:
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect("127.0.0.1", 1883, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            print(f"[MQTT] Reconnexion dans 5s... ({exc})")
            time.sleep(5)


# ── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    threading.Thread(target=mqtt_thread, daemon=True).start()
    print("[SERVER] Demarrage sur http://0.0.0.0:5000")
    sio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)
