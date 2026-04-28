import json
import paho.mqtt.client as mqtt
import numpy as np
import joblib
from collections import deque
from datetime import datetime, timezone
import os

# --- CONFIGURATION MQTT GLOBALE ---
MQTT_BROKER = "localhost" 
MQTT_PORT = 1883
MQTT_TOPIC = "pfa/smartparking/rsu01"

class ServeurEdge:
    def __init__(self, config_file, model_path=None):
        print(f"📂 Chargement de la configuration depuis {config_file}...")
        with open(config_file, 'r') as f:
            self.config = json.load(f)
            
        self.metadata = self.config["metadata"]
        self.spots_mapping = self.config["spots_mapping"]
        self.etat_places = {}
        
        # 1. Détection automatique de TOUTES les places via la grille
        for ligne in self.config["grid"]:
            for cellule in ligne:
                # CORRECTION : On cible les IDs de 10 à 90, en excluant 98 et 99
                if 10 <= cellule <= 90 and cellule != 98 and cellule != 99:
                    self.etat_places[cellule] = "UNAVAILABLE"
                    
        # 2. Initialisation des places équipées
        for spot_id_str in self.spots_mapping.keys():
            spot_id = int(spot_id_str)
            if spot_id in self.etat_places:
                self.etat_places[spot_id] = "UNKNOWN"
        
        # 3. Initialisation du système de détection d'anomalies
        self.historiques = {}
        self.modele_if = None
        
        if model_path is None:
            model_path = os.path.join(os.path.dirname(__file__), "isolation_forest.pkl")
        
        if os.path.exists(model_path):
            try:
                self.modele_if = joblib.load(model_path)
                print(f"✅ Modèle ML chargé : {model_path}")
            except Exception as e:
                print(f"⚠️ Impossible de charger le modèle ML : {e}")
        else:
            print(f"⚠️ Modèle ML non trouvé : {model_path}")
                
        print(f"✅ Configuration chargée: {self.metadata['name']}")
        print(f"🚗 Places totales : {len(self.etat_places)} | 📡 Équipées : {len(self.spots_mapping)}")

    def get_historique(self, place_id):
        if place_id not in self.historiques:
            self.historiques[place_id] = {
                "distances":  deque(maxlen=60),
                "timestamps": deque(maxlen=60),
            }
        return self.historiques[place_id]

    def ajouter_mesure(self, place_id, distance, timestamp=None):
        h = self.get_historique(place_id)
        h["distances"].append(float(distance))
        h["timestamps"].append(timestamp or datetime.now(timezone.utc))

    def check_zscore(self, distance, place_id, seuil=3.0):
        h = self.get_historique(place_id)
        if len(h["distances"]) < 10: return False
        historique = list(h["distances"])
        moyenne, ecart = np.mean(historique), np.std(historique)
        if ecart == 0: return True
        return abs((float(distance) - moyenne) / ecart) > seuil

    def check_isolation_forest(self, distance, place_id):
        if self.modele_if is None: return False
        h = self.get_historique(place_id)
        distances = list(h["distances"])
        f1 = float(distance)
        window = distances[-10:] + [f1]
        f2 = float(np.std(window)) if len(window) > 1 else 0.0
        f3 = abs(f1 - distances[-1]) if len(distances) > 0 else 0.0
        try:
            return self.modele_if.predict([[f1, f2, f3]])[0] == -1
        except: return False

    def check_business_rules(self, distance, place_id):
        h = self.get_historique(place_id)
        distances = list(h["distances"])
        dist = float(distance)
        if dist < 2.0 or dist > 20.0: return True
        if len(distances) >= 2 and abs(dist - distances[-2]) > 50.0: return True
        return False

    def vote_majoritaire(self, distance, place_id):
        r1 = self.check_zscore(distance, place_id)
        r2 = self.check_isolation_forest(distance, place_id)
        r3 = self.check_business_rules(distance, place_id)
        return {"anomalie": (sum([r1, r2, r3]) >= 2), "votes": sum([r1, r2, r3])}

    def analyser_anomalies(self, spot_id, distance):
        self.ajouter_mesure(spot_id, distance)
        return self.vote_majoritaire(distance, spot_id)
    
    def sauvegarder_etat_direct(self):
        donnees = {
            "derniere_mise_a_jour": datetime.now(timezone.utc).isoformat(),
            "places": self.etat_places
        }
        with open("etat_parking.json", 'w', encoding='utf-8') as f:
            json.dump(donnees, f, indent=4)

    def log_evenement(self, type_event, spot_id, detail):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type_event,
            "spot_id": spot_id,
            "details": detail
        }
        with open("historique.jsonl", 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')

    def traiter_cpm(self, payload_json):
        try:
            data = json.loads(payload_json)
            places_array = data.get("places", [])
            distances_array = data.get("distances", [])
            anomalies_detectees = []
            
            for index, etat in enumerate(places_array):
                hardware_id = index + 1 
                status = "OCCUPIED" if etat == 1 else "FREE"
                
                for spot_id_str, map_data in self.spots_mapping.items():
                    if map_data["hardware_id"] == hardware_id:
                        spot_id = int(spot_id_str)
                        
                        etat_precedent = self.etat_places.get(spot_id)
                        self.etat_places[spot_id] = status
                        
                        if etat_precedent != status and etat_precedent not in ["UNKNOWN", "UNAVAILABLE"]:
                            self.log_evenement("CHANGEMENT_ETAT", spot_id, f"Passage à {status}")
                        
                        if distances_array and index < len(distances_array):
                            dist = float(distances_array[index])
                            res = self.analyser_anomalies(spot_id, dist)
                            if res["anomalie"]:
                                anomalies_detectees.append(spot_id)
                                self.log_evenement("ANOMALIE", spot_id, f"Distance: {dist}cm (Votes:{res['votes']}/3)")
                        break 
            
            self.sauvegarder_etat_direct()
            print(f"🔄 Mise à jour : {len([v for v in self.etat_places.values() if v=='FREE'])} libres")
            
        except Exception as e:
            print(f"❌ Erreur : {e}")

# --- LANCEMENT ---
serveur = ServeurEdge('conf_parking.json')

def on_message(c, u, msg): serveur.traiter_cpm(msg.payload.decode())
def on_connect(c, u, f, rc): 
    if rc == 0: c.subscribe(MQTT_TOPIC)
    print("✅ Connecté" if rc==0 else f"❌ Erreur {rc}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "Edge_Backend")
client.on_message = on_message
client.on_connect = on_connect

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print(f"👂 Écoute sur {MQTT_TOPIC}...")
    client.loop_forever()
except Exception as e:
    print(f"❌ Erreur connexion : {e}")