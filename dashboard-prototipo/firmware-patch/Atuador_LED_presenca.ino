/* NÓ ATUADOR — 4 Níveis de Luz (Com Confirmação de Estado para N1)
 *               (+ presença opcional para o dashboard)
 *
 * PATCH ADITIVO sobre Atuador_LED/Atuador_LED.ino. A lógica dos LEDs, o tópico
 * de comando, o tópico/formato de status e o DEVICE_ID não foram alterados.
 *
 * ACRESCENTADO (// [+]): iot/luzambiente/atuador/conexao (retido)
 *   {"device":"atuador01","status":"online"} ao conectar e LWT "offline".
 * Permite ao dashboard distinguir "atuador desligado" de "nenhum comando
 * para confirmar".
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#define WIFI_SSID "SUA_REDE"
#define WIFI_PASSWORD "SUA_SENHA"
#define MQTT_HOST "broker.hivemq.com"
#define MQTT_PORT 1883

constexpr uint8_t PIN_LED_AMBIENTE = 27; // LED 1
constexpr uint8_t PIN_LED_ESCURO   = 26; // LED 2
constexpr uint8_t PIN_LED_ALTA     = 25; // LED 3
constexpr uint8_t PIN_LED_EXTREMA  = 33; // LED 4

#define BASE "iot/luzambiente"
constexpr char TOPICO_COMANDO[] = BASE "/atuador/luz/comando";
constexpr char TOPICO_STATUS[] = BASE "/atuador/status";
constexpr char TOPICO_CONEXAO[] = BASE "/atuador/conexao";                                   // [+]
constexpr char PAYLOAD_ONLINE[] = "{\"device\":\"atuador01\",\"status\":\"online\"}";     // [+]
constexpr char PAYLOAD_OFFLINE[] = "{\"device\":\"atuador01\",\"status\":\"offline\"}";   // [+]
constexpr char DEVICE_ID[] = "atuador01";

char cenaAtual[16] = "apagada";

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void desligarTodos() {
  digitalWrite(PIN_LED_AMBIENTE, LOW);
  digitalWrite(PIN_LED_ESCURO, LOW);
  digitalWrite(PIN_LED_ALTA, LOW);
  digitalWrite(PIN_LED_EXTREMA, LOW);
}

void publicarStatus() {
  char payload[128];
  snprintf(payload, sizeof(payload), "{\"device\":\"%s\",\"estado\":\"%s_executada\"}", DEVICE_ID, cenaAtual);
  mqtt.publish(TOPICO_STATUS, payload, true);
  Serial.printf("Status publicado: %s\n", payload);
}

void onMessage(char* topic, byte* bytes, unsigned int length) {
  JsonDocument doc;
  if (deserializeJson(doc, bytes, length)) {
    Serial.println("Comando JSON inválido.");
    return;
  }

  const char* novaCena = doc["cena"] | "apagada";
  strlcpy(cenaAtual, novaCena, sizeof(cenaAtual));
  Serial.printf("Cena recebida: %s\n", cenaAtual);

  desligarTodos();

  if (strcmp(cenaAtual, "escuro") == 0) {
    digitalWrite(PIN_LED_ESCURO, HIGH);
  }
  else if (strcmp(cenaAtual, "ambiente") == 0) {
    digitalWrite(PIN_LED_AMBIENTE, HIGH);
  }
  else if (strcmp(cenaAtual, "alta") == 0) {
    digitalWrite(PIN_LED_ALTA, HIGH);
  }
  else if (strcmp(cenaAtual, "extrema") == 0) {
    digitalWrite(PIN_LED_AMBIENTE, HIGH);
    digitalWrite(PIN_LED_ESCURO, HIGH);
    digitalWrite(PIN_LED_ALTA, HIGH);
    digitalWrite(PIN_LED_EXTREMA, HIGH);
  }

  publicarStatus();
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("WiFi");
    while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
    Serial.println(" OK!");
  }
  if (!mqtt.connected()) {
    while (!mqtt.connect(DEVICE_ID, TOPICO_CONEXAO, 1, true, PAYLOAD_OFFLINE)) { delay(1000); }  // [+] LWT
    mqtt.publish(TOPICO_CONEXAO, PAYLOAD_ONLINE, true);                                          // [+]
    mqtt.subscribe(TOPICO_COMANDO, 1);
    Serial.println("MQTT OK! À escuta...");
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_LED_AMBIENTE, OUTPUT);
  pinMode(PIN_LED_ESCURO, OUTPUT);
  pinMode(PIN_LED_ALTA, OUTPUT);
  pinMode(PIN_LED_EXTREMA, OUTPUT);
  desligarTodos();

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  conectar();
  mqtt.loop();
}
