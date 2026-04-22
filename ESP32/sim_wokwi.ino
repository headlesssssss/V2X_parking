#include <WiFi.h>
#include <PubSubClient.h>

#define NUM_PLACES 8

// --- CONFIGURATION PARKING ---
const int trigPins[NUM_PLACES] = {4, 5, 15, 16, 17, 18, 19, 21};
const int echoPins[NUM_PLACES] = {12, 13, 14, 25, 26, 27, 32, 33};
int etatsPlaces[NUM_PLACES] = {0, 0, 0, 0, 0, 0, 0, 0};
const int SEUIL_OCCUPATION = 10; 
const int DISTANCE_MUR = 40;     

// --- CONFIGURATION RESEAU (Wokwi Wi-Fi & MQTT) ---
const char* ssid = "Wokwi-GUEST"; // Réseau virtuel Wokwi
const char* password = "";        // Pas de mot de passe
const char* mqtt_server = "broker.hivemq.com"; // Broker MQTT public gratuit
const char* mqtt_topic = "pfa/smartparking/rsu01"; // L'adresse où on envoie les données

WiFiClient espClient;
PubSubClient client(espClient);

// Fonction pour se connecter au Wi-Fi
void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connexion a ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connecte !");
}

// Fonction pour se (re)connecter au Broker MQTT
void reconnect() {
  while (!client.connected()) {
    Serial.print("Tentative de connexion MQTT...");
    // Création d'un ID client aléatoire
    String clientId = "RSU-Client-";
    clientId += String(random(0xffff), HEX);
    
    if (client.connect(clientId.c_str())) {
      Serial.println("Connecte au Broker !");
    } else {
      Serial.print("Echec, rc=");
      Serial.print(client.state());
      Serial.println(" nouvel essai dans 5 secondes");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  
  // Initialisation des broches
  for (int i = 0; i < NUM_PLACES; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
    digitalWrite(trigPins[i], LOW);
  }

  // Initialisation Réseau
  setup_wifi();
  client.setServer(mqtt_server, 1883);
}

void loop() {
  // Vérification de la connexion MQTT
  if (!client.connected()) {
    reconnect();
  }
  client.loop(); // Maintient la connexion active

  // 1. PHASE DE LECTURE
  for (int i = 0; i < NUM_PLACES; i++) {
    digitalWrite(trigPins[i], HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPins[i], LOW);

    long duration = pulseIn(echoPins[i], HIGH, 30000); 
    float distance_cm = (duration == 0) ? DISTANCE_MUR : (duration * 0.0343) / 2.0;

    // 2. PHASE D'ANALYSE
    if (distance_cm > 0 && distance_cm <= SEUIL_OCCUPATION) {
      etatsPlaces[i] = 1; 
    } else {
      etatsPlaces[i] = 0; 
    }
    delay(10); 
  }

  // 3. PHASE DE FORMATAGE JSON
  String cpm_payload = "{";
  cpm_payload += "\"rsu_id\": \"RSU_ESP32_01\", ";
  cpm_payload += "\"timestamp\": " + String(millis()) + ", ";
  cpm_payload += "\"places\": [";
  
  for (int i = 0; i < NUM_PLACES; i++) {
    cpm_payload += String(etatsPlaces[i]);
    if (i < NUM_PLACES - 1) cpm_payload += ", ";
  }
  cpm_payload += "]}";

  // 4. PUBLICATION MQTT (Envoi sur internet)
  Serial.println("Envoi MQTT : " + cpm_payload);
  
  // On convertit la String en tableau de char (requis par PubSubClient)
  client.publish(mqtt_topic, cpm_payload.c_str());

  delay(2000);
}