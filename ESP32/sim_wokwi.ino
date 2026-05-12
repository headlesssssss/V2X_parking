#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// --- CONFIGURATION WIFI & MQTT ---
const char* ssid = "TON_SSID_WIFI"; // À modifier pour ton routeur local
const char* password = "TON_MOT_DE_PASSE"; // À modifier
const char* mqtt_server = "IP_DE_TON_SERVEUR_EDGE"; // L'adresse IP de ton PC/Raspberry Pi
const int mqtt_port = 1883;
const char* mqtt_topic = "pfa/smartparking/rsu01";
const char* rsu_id = "RSU_ESP32_01";

WiFiClient espClient;
PubSubClient client(espClient);

// --- NOUVELLES BROCHES (Selon ton image) ---
const int NUM_SENSORS = 4;
const int TRIG_PINS[NUM_SENSORS] = {5, 13, 17, 25};
const int ECHO_PINS[NUM_SENSORS] = {18, 14, 16, 26};

float distances[NUM_SENSORS];
int places[NUM_SENSORS];
const float DISTANCE_SEUIL = 03.0; // cm

void setup_wifi() {
  delay(10);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }
}

void reconnect() {
  while (!client.connected()) {
    if (client.connect(rsu_id)) {
      // Connecté au broker
    } else {
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  
  // Initialisation des 4 capteurs
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);
  }
  
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  
  // Maintien du buffer élargi pour la sécurité MQTT
  client.setBufferSize(1024); 
}

float mesurerDistance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  
  long duration = pulseIn(echoPin, HIGH, 30000); 
  
  if (duration == 0) return 400.0;
  return (duration * 0.0343) / 2.0;
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  Serial.println("\n--- 📡 NOUVELLE MESURE ---");

  // 1. Lecture des 4 capteurs
  for (int i = 0; i < NUM_SENSORS; i++) {
    distances[i] = mesurerDistance(TRIG_PINS[i], ECHO_PINS[i]);
    places[i] = (distances[i] < DISTANCE_SEUIL) ? 1 : 0;
    
    Serial.print("Capteur C"); Serial.print(i+1);
    Serial.print(" : "); Serial.print(distances[i]); Serial.println(" cm");
    
    delay(20);
  }

  // 2. Création du JSON
  DynamicJsonDocument doc(1024);
  doc["rsu_id"] = rsu_id;
  doc["timestamp"] = millis();

  JsonArray places_array = doc.createNestedArray("places");
  JsonArray distances_array = doc.createNestedArray("distances");

  for (int i = 0; i < NUM_SENSORS; i++) {
    places_array.add(places[i]);
    float dist_arrondie = ((int)(distances[i] * 10)) / 10.0;
    distances_array.add(dist_arrondie);
  }

  // 3. Envoi MQTT
  String payload;
  serializeJson(doc, payload);
  Serial.println("Trame envoyee : " + payload);
  client.publish(mqtt_topic, payload.c_str());

  delay(2000);
}
