import json
import paho.mqtt.client as mqtt

class ServeurEdge:
    def __init__(self, config_file):
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
                
        print(f"✅ Configuration chargée: {self.metadata['name']}")
        print(f"🚗 Nombre total de places détectées : {len(self.etat_places)}")
        print(f"📡 Nombre de places équipées de capteurs : {len(self.spots_mapping)}")

    def traiter_cpm(self, payload_json):
        """Met à jour l'état en mémoire lors de la réception d'un CPM de l'ESP32."""
        try:
            data = json.loads(payload_json)
            
            # On récupère le tableau envoyé par l'ESP32 (ex: [1, 0, 0, 0, 0, 0, 0, 0])
            places_array = data.get("places", [])
            
            # On parcourt ce tableau en associant l'index au capteur physique
            # Index 0 = capteur 1, Index 1 = capteur 2, etc.
            for index, etat in enumerate(places_array):
                hardware_id = index + 1 
                
                # Traduction de l'entier (0 ou 1) en statut textuel
                status = "OCCUPIED" if etat == 1 else "FREE"
                
                # Recherche de la place (ex: 10 à 25) liée à ce capteur (1 à 8)
                for spot_id_str, map_data in self.spots_mapping.items():
                    if map_data["hardware_id"] == hardware_id:
                        spot_id = int(spot_id_str)
                        self.etat_places[spot_id] = status
                        break 
            
            # Affichage en temps réel
            places_libres = [k for k, v in self.etat_places.items() if v == "FREE"]
            print(f"🔄 Mise à jour LDM ! Places libres : {places_libres}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la lecture du JSON MQTT: {e}")

# Instanciation de la carte
serveur = ServeurEdge('conf_parking.json')

def on_message(client, userdata, msg):
    """Fonction déclenchée à chaque message MQTT reçu."""
    # On vérifie si le topic correspond à notre RSU Wokwi
    if msg.topic == "pfa/smartparking/rsu01":
        serveur.traiter_cpm(msg.payload.decode())

# CORRECTION PAHO MQTT v2.0
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="Serveur_Edge_Backend")
client.on_message = on_message

# Mise à jour avec le Broker Public HiveMQ
MQTT_BROKER = "broker.hivemq.com"
print(f"\n⏳ Connexion au Broker MQTT public ({MQTT_BROKER})...")
client.connect(MQTT_BROKER, 1883, 60)

# On s'abonne au topic spécifique de notre simulation ESP32
MQTT_TOPIC = "pfa/smartparking/rsu01"
client.subscribe(MQTT_TOPIC)

print(f"👂 Serveur Edge en écoute sur {MQTT_TOPIC}...")
client.loop_forever()