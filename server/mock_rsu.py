"""
Simulateur 4 capteurs HC-SR04 pour la maquette Smart Parking V2X.

    C1 (hw=1) → spot 17  bas-gauche
    C2 (hw=2) → spot 12  haut-gauche
    C3 (hw=3) → spot 22  bas-droite
    C4 (hw=4) → spot 16  haut-droite

Seuil maquette : distance < 4 cm = place occupee.
Bruit gaussien + transitions d etat + injection d anomalies periodiques.
"""

import json
import random
import time
import paho.mqtt.client as mqtt

BROKER    = "127.0.0.1"
PORT      = 1883
INTERVAL  = 2.0        # secondes entre chaque publication
THRESHOLD = 4.0        # cm

# Distances representant les etats physiques de la maquette (8x6.5 cm)
DIST_OCCUPIED = 2.0    # cm  — voiture presente
DIST_FREE     = 7.0    # cm  — place vide
NOISE_STD     = 0.15   # ecart-type du bruit


class SensorSim:
    """Simule un capteur HC-SR04 avec bruit, transitions et anomalies."""

    def __init__(self, hw_id: int, initial: str = "FREE"):
        self.hw_id       = hw_id
        self.state       = initial
        self.tick        = 0
        self.hold        = 0          # nombre de ticks restants avant autorisation de changement
        self._anom_left  = 0          # ticks d anomalie restants

    def _transition(self):
        """Change d etat avec une probabilite de 4 % si le hold est ecoule."""
        if self.hold > 0:
            self.hold -= 1
            return
        if random.random() < 0.04:
            self.state = "FREE" if self.state == "OCCUPIED" else "OCCUPIED"
            self.hold  = random.randint(10, 25)   # maintien min 20-50 s

    def measure(self) -> float:
        self.tick += 1
        self._transition()

        # Injection d anomalie : capteur mort (distance < 0.5)
        if self.hw_id == 1 and self.tick % 80 == 0:
            self._anom_left = random.randint(3, 6)

        # Anomalie : valeur hors plage physique
        if self.hw_id == 3 and self.tick % 60 == 0:
            return round(random.uniform(11.0, 13.0), 2)   # hors portee

        if self._anom_left > 0:
            self._anom_left -= 1
            return round(random.uniform(0.1, 0.4), 2)     # capteur mort

        base  = DIST_OCCUPIED if self.state == "OCCUPIED" else DIST_FREE
        noise = random.gauss(0, NOISE_STD)
        raw   = base + noise

        # Contraindre dans la plage physique valide de la maquette
        raw = max(0.5, min(9.5, raw))
        return round(raw, 2)


sensors = [
    SensorSim(1, "OCCUPIED"),
    SensorSim(2, "FREE"),
    SensorSim(3, "FREE"),
    SensorSim(4, "OCCUPIED"),
]


def on_connect(client, userdata, flags, rc, *args):
    print(f"[RSU] Connecte au broker MQTT {BROKER}:{PORT}  (rc={rc})")


def build_client() -> mqtt.Client:
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="mock_rsu_esp32cam")
    except AttributeError:
        c = mqtt.Client(client_id="mock_rsu_esp32cam")
    c.on_connect = on_connect
    return c


def main():
    client = build_client()
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    print("[RSU] Simulateur 4 capteurs demarre")
    print(f"[RSU] Topics : parking/{{1..4}}/cpm  |  seuil = {THRESHOLD} cm")
    print("[RSU] Ctrl+C pour arreter\n")

    try:
        while True:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for sensor in sensors:
                dist = sensor.measure()
                etat = "OCCUPIED" if dist < THRESHOLD else "FREE"

                payload = json.dumps({
                    "hardware_id":  sensor.hw_id,
                    "distance_cm":  dist,
                    "timestamp":    ts,
                })
                topic = f"parking/{sensor.hw_id}/cpm"
                client.publish(topic, payload, qos=0)

                flag = "!" if dist < 0.5 or dist > 10 else " "
                print(f"  [{flag}] hw{sensor.hw_id}  {dist:5.2f} cm  {etat:<8}  "
                      f"-> {topic}")

            print()
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\n[RSU] Arret du simulateur")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
