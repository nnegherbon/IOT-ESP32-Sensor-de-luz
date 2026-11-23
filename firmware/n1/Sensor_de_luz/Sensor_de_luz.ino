/* NÓ SENSOR — 4 Níveis de Luz */
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

#define WIFI_SSID "SUA_REDE"      // credencial removida do repositório (R9)
#define WIFI_PASSWORD "SUA_SENHA"  // credencial removida do repositório (R9)
#define MQTT_HOST "192.168.100.7"  // IP do PC com o Docker (broker Mosquitto local)
#define MQTT_PORT 1883

const int PINO_SENSOR = 34; 
const char TOPICO_COMANDO[] = "iot/luzambiente/atuador/luz/comando";
// Telemetria (leitura bruta do LDR) e presença para a dashboard
const char TOPICO_TELEMETRIA[] = "iot/luzambiente/sensor/telemetria";
const char TOPICO_CONEXAO[] = "iot/luzambiente/sensor/conexao";   // retido; "offline" via LWT
const char CLIENT_ID[] = "SensorNode01";
const char PAYLOAD_ONLINE[] = "{\"device\":\"SensorNode01\",\"status\":\"online\"}";
const char PAYLOAD_OFFLINE[] = "{\"device\":\"SensorNode01\",\"status\":\"offline\"}";
const unsigned long TELEMETRIA_INTERVALO_MS = 2000;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);


String cenaAtual = "";
unsigned long ultimaTelemetria = 0;

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("WiFi");
    unsigned long inicio = millis();
    while (WiFi.status() != WL_CONNECTED) {
      delay(500); Serial.print(".");
      // Não espera para sempre: depois de 15 s recomeça a conexão (antes travava após quedas/reinícios)
      if (millis() - inicio > 15000) {
        Serial.println(" tentando de novo");
        WiFi.disconnect(true); delay(500);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        inicio = millis();
      }
    }
    Serial.println(" OK!");
  }
  if (!mqtt.connected()) {
    // LWT: se o sensor cair sem desconectar, o broker publica "offline" (retido)
    while (!mqtt.connect(CLIENT_ID, TOPICO_CONEXAO, 1, true, PAYLOAD_OFFLINE)) {
      if (WiFi.status() != WL_CONNECTED) return;  // Wi-Fi caiu: o próximo loop reconecta
      delay(2000);
    }
    mqtt.publish(TOPICO_CONEXAO, PAYLOAD_ONLINE, true);
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

// Telemetria periódica: leitura bruta (0–4095) e cena atual, para mín/máx/média e o gráfico
void enviarTelemetria(int leitura, const String& cena) {
  unsigned long agora = millis();
  if (agora - ultimaTelemetria < TELEMETRIA_INTERVALO_MS) return;
  ultimaTelemetria = agora;
  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"leitura\":%d,\"cena\":\"%s\",\"uptime_ms\":%lu}",
           CLIENT_ID, leitura, cena.c_str(), agora);
  mqtt.publish(TOPICO_TELEMETRIA, payload);
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

  enviarTelemetria(leitura, cenaAtual);

  delay(300); // Ligeiramente mais rápido para reagir à lanterna
}