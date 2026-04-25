import json
import paho.mqtt.client as mqtt
import numpy as np
import joblib
from collections import deque
from datetime import datetime, timezone
import os

# --- CONFIGURATION MQTT GLOBALE ---
MQTT_BROKER = "localhost" # change to local broker
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
                # Tout nombre >= 10 (sauf 99) est une place
                if cellule >= 10 and cellule != 99:
                    self.etat_places[cellule] = "UNAVAILABLE"
                    
        # 2. Initialisation des places équipées
        for spot_id_str in self.spots_mapping.keys():
            spot_id = int(spot_id_str)
            if spot_id in self.etat_places:
                self.etat_places[spot_id] = "UNKNOWN"
        
        # 3. Initialisation du système de détection d'anomalies
        self.historiques = {}
        self.modele_if = None
        
        # Charge le modèle ML si disponible
        if model_path is None:
            model_path = os.path.join(os.path.dirname(__file__), "isolation_forest.pkl")
        
        if os.path.exists(model_path):
            try:
                self.modele_if = joblib.load(model_path)
                print(f"✅ Modèle ML chargé : {model_path}")
            except Exception as e:
                print(f"⚠️ Impossible de charger le modèle ML : {e}")
        else:
            print(f"⚠️ Modèle ML non trouvé : {model_path} (L'inférence sera ignorée)")
                
        print(f"✅ Configuration chargée: {self.metadata['name']}")
        print(f"🚗 Nombre total de places : {len(self.etat_places)} | 📡 Équipées : {len(self.spots_mapping)}")

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
        if len(h["distances"]) < 10:
            return False
        historique = list(h["distances"])
        moyenne = np.mean(historique)
        ecart   = np.std(historique)
        if ecart == 0:
            return True
        z = abs((float(distance) - moyenne) / ecart)
        return z > seuil

    def check_isolation_forest(self, distance, place_id):
        if self.modele_if is None:
            return False
        
        h = self.get_historique(place_id)
        distances = list(h["distances"])
        
        f1 = float(distance)
        window = distances[-10:] + [float(distance)]
        f2 = float(np.std(window)) if len(window) > 1 else 0.0
        f3 = abs(float(distance) - distances[-1]) if len(distances) > 0 else 0.0
        
        try:
            prediction = self.modele_if.predict([[f1, f2, f3]])[0]
            return prediction == -1
        except Exception as e:
            return False

    def check_business_rules(self, distance, place_id, frozen_min=10, frozen_seconds=10):
        h = self.get_historique(place_id)
        distances  = list(h["distances"])
        timestamps = list(h["timestamps"])
        distance = float(distance)

        # Règle 1 : Distance impossible pour un HC-SR04 dans notre contexte Wokwi (en cm)
        if distance < 2.0 or distance > 20.0:
            return True

        # Règle 2 : Oscillation brutale (saut de plus de 50 cm d'un coup)
        if len(distances) >= 2:
            delta = abs(distance - distances[-2])
            if delta > 50.0:
                return True

        # Règle 3 : Valeur figée (capteur bloqué)
        if len(distances) >= frozen_min:
            derniers = distances[-frozen_min:]
            if max(derniers) - min(derniers) < 0.05:
                if len(timestamps) >= frozen_min:
                    duree = (timestamps[-1] - timestamps[-frozen_min]).total_seconds()
                    if duree >= frozen_seconds:
                        return True

        return False

    def vote_majoritaire(self, distance, place_id):
        r1 = self.check_zscore(distance=distance, place_id=place_id)
        r2 = self.check_isolation_forest(distance=distance, place_id=place_id)
        r3 = self.check_business_rules(distance=distance, place_id=place_id)
        votes = sum([r1, r2, r3])
        return {
            "anomalie":         votes >= 2,
            "votes":            votes,
            "zscore":           r1,
            "isolation_forest": r2,
            "business_rules":   r3,
        }

    def analyser_anomalies(self, spot_id, distance):
        self.ajouter_mesure(spot_id, distance)
        resultat = self.vote_majoritaire(distance, spot_id)
        
        if resultat["anomalie"]:
            print(f"⚠️ ANOMALIE DÉTECTÉE - Spot {spot_id}: dist={distance:.1f}cm, votes={resultat['votes']}/3 (Z:{resultat['zscore']} | IF:{resultat['isolation_forest']} | Rules:{resultat['business_rules']})")
        
        return resultat
    
    def sauvegarder_etat_direct(self):
        """Exporte l'état actuel pour que le Dashboard Web puisse le lire"""
        chemin_fichier = "etat_parking.json"
        
        donnees_export = {
            "derniere_mise_a_jour": datetime.now(timezone.utc).isoformat(),
            "places": self.etat_places
        }
        
        # 'w' écrase le fichier à chaque fois pour n'avoir que le temps réel
        with open(chemin_fichier, 'w', encoding='utf-8') as f:
            json.dump(donnees_export, f, indent=4)

    def log_evenement(self, type_event, spot_id, detail):
        """Ajoute une ligne de log dans l'historique"""
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
            
            # FALLBACK WOKWI : Si l'ESP32 n'envoie pas encore le tableau "distances"
            if not distances_array and places_array:
                # On simule une distance cohérente pour faire tourner les algorithmes
                distances_array = [8.0 if etat == 1 else 40.0 for etat in places_array]

            anomalies_detectees = []
            
            for index, etat in enumerate(places_array):
                hardware_id = index + 1 
                status = "OCCUPIED" if etat == 1 else "FREE"
                
                for spot_id_str, map_data in self.spots_mapping.items():
                    if map_data["hardware_id"] == hardware_id:
                        spot_id = int(spot_id_str)
                        self.etat_places[spot_id] = status
                        
                        # Analyse IA des distances
                        if distances_array and index < len(distances_array):
                            distance = float(distances_array[index])
                            resultat_anomalie = self.analyser_anomalies(spot_id, distance)
                            if resultat_anomalie["anomalie"]:
                                anomalies_detectees.append(spot_id)
                                # L'enregistrement de l'anomalie dans l'historique se fait ici
                                self.log_evenement("ANOMALIE", spot_id, f"Distance aberrante: {distance}cm")
                        break 
            
            places_libres = [k for k, v in self.etat_places.items() if v == "FREE"]
            places_occupees = [k for k, v in self.etat_places.items() if v == "OCCUPIED"]
            
            print(f"\n🔄 LDM: Libres: {places_libres} | Occupées: {places_occupees}")
            if anomalies_detectees:
                print(f"   🚨 Anomalies ignorées par le système sur les places : {anomalies_detectees}")

            self.sauvegarder_etat_direct()
        except Exception as e:
            print(f"❌ Erreur MQTT JSON : {e}")

# --- LANCEMENT DU SCRIPT ---
serveur = ServeurEdge('conf_parking.json')

def on_message(client, userdata, msg):
    if msg.topic == MQTT_TOPIC:
        serveur.traiter_cpm(msg.payload.decode())

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connecté à {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"❌ Erreur, code {rc}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="Serveur_Edge_Backend")
client.on_message = on_message
client.on_connect = on_connect

print(f"\n⏳ Connexion au Broker MQTT public ({MQTT_BROKER})...")
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
except Exception as e:
    print(f"❌ Impossible de se connecter : {e}")
    exit(1)

print(f"👂 Serveur Edge en écoute sur : {MQTT_TOPIC}")
print("=" * 70)
client.loop_forever()