/* NÓ SENSOR — 4 Níveis de Luz  (+ telemetria opcional para o dashboard)
 *
 * PATCH ADITIVO sobre Sensor_de_luz/Sensor_de_luz.ino. Nada do comportamento
 * original foi alterado:
 *   - mesmo tópico de comando, mesmo payload {"cena":"..."};
 *   - mesmos limites (150 / 400 / 1000) e mesma regra "só publica na mudança";
 *   - mesmo client ID (SensorNode01).
 *
 * O que foi ACRESCENTADO (marcado com // [+]):
 *   1. iot/luzambiente/sensor/telemetria
 *        {"device":"SensorNode01","leitura":<0..4095>,"cena":"<cena>","uptime_ms":<millis>}
 *        a cada TELEMETRIA_INTERVALO_MS. Permite ao dashboard mostrar o valor
 *        bruto do LDR, mín/máx/média e alertas por limite.
 *   2. iot/luzambiente/sensor/conexao (retido)
 *        {"device":"SensorNode01","status":"online"} ao conectar e, via LWT,
 *        {"device":"SensorNode01","status":"offline"} quando a conexão cai.
 *
 * Justificativa técnica: o firmware original só imprime a leitura na Serial,
 * então ela não chega a nenhum outro sistema. Sem este patch o dashboard
 * continua funcionando, apenas sem a leitura bruta e sem presença.
 *
 * Credenciais: mantenha WIFI_SSID / WIFI_PASSWORD fora do repositório
 * (ex.: um secrets.h listado no .gitignore).
 */
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

#define WIFI_SSID "SUA_REDE"
#define WIFI_PASSWORD "SUA_SENHA"
#define MQTT_HOST "broker.hivemq.com"
#define MQTT_PORT 1883

const int PINO_SENSOR = 34;
const char TOPICO_COMANDO[] = "iot/luzambiente/atuador/luz/comando";
const char TOPICO_TELEMETRIA[] = "iot/luzambiente/sensor/telemetria";  // [+]
const char TOPICO_CONEXAO[] = "iot/luzambiente/sensor/conexao";        // [+]
const char CLIENT_ID[] = "SensorNode01";
const char PAYLOAD_ONLINE[] = "{\"device\":\"SensorNode01\",\"status\":\"online\"}";    // [+]
const char PAYLOAD_OFFLINE[] = "{\"device\":\"SensorNode01\",\"status\":\"offline\"}";  // [+]
const unsigned long TELEMETRIA_INTERVALO_MS = 2000;                    // [+]

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

String cenaAtual = "";
unsigned long ultimaTelemetria = 0;  // [+]

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("WiFi");
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.println(" OK!");
  }
  if (!mqtt.connected()) {
    // [+] LWT: o broker publica "offline" (retido) se o sensor cair sem desconectar
    while (!mqtt.connect(CLIENT_ID, TOPICO_CONEXAO, 1, true, PAYLOAD_OFFLINE)) { delay(2000); }
    mqtt.publish(TOPICO_CONEXAO, PAYLOAD_ONLINE, true);  // [+]
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

// [+] Telemetria periódica com a leitura bruta e a cena calculada
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

  // LIMITES AJUSTADOS PARA RESPONDER MAIS CEDO (inalterados)
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

  enviarTelemetria(leitura, cenaAtual);  // [+]

  delay(300); // Ligeiramente mais rápido para reagir à lanterna
}
