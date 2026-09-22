/* NÓ SENSOR — 4 Níveis de Luz */
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

#define WIFI_SSID "IPhone vinícius Clemente"
#define WIFI_PASSWORD "123456780301"
#define MQTT_HOST "broker.hivemq.com"
#define MQTT_PORT 1883

const int PINO_SENSOR = 34; 
const char TOPICO_COMANDO[] = "iot/luzambiente/atuador/luz/comando";

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

String cenaAtual = "";

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("WiFi");
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.println(" OK!");
  }
  if (!mqtt.connected()) {
    while (!mqtt.connect("SensorNode01")) { delay(2000); }
    Serial.println("MQTT OK!");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_SENSOR, INPUT);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void enviarCena(String novaCena) {
  if (cenaAtual != novaCena) {
    String payload = "{\"cena\":\"" + novaCena + "\"}";
    mqtt.publish(TOPICO_COMANDO, payload.c_str());
    Serial.println("Mudança detetada! Comando enviado: " + novaCena);
    cenaAtual = novaCena;
  }
}

void loop() {
  conectar();
  mqtt.loop();

  int leitura = analogRead(PINO_SENSOR);
  Serial.printf("Luz: %d\n", leitura);

  // LIMITES AJUSTADOS PARA RESPONDER MAIS CEDO
  if (leitura < 150) { 
    enviarCena("escuro"); 
  } 
  else if (leitura >= 150 && leitura < 400) { 
    enviarCena("ambiente"); 
  } 
  else if (leitura >= 400 && leitura < 1000) { 
    enviarCena("alta"); 
  } 
  else if (leitura >= 1000) { 
    enviarCena("extrema"); 
  }
  
  delay(300); // Ligeiramente mais rápido para reagir à lanterna
}