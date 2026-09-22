/* NÓ ATUADOR — 4 Níveis de Luz (Com Confirmação de Estado para N1) */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#define WIFI_SSID "IPhone vinícius Clemente"
#define WIFI_PASSWORD "123456780301"
#define MQTT_HOST "broker.hivemq.com"
#define MQTT_PORT 1883

// Definição dos pinos saudáveis
constexpr uint8_t PIN_LED_AMBIENTE = 27; // LED 1
constexpr uint8_t PIN_LED_ESCURO   = 26; // LED 2
constexpr uint8_t PIN_LED_ALTA     = 25; // LED 3
constexpr uint8_t PIN_LED_EXTREMA  = 33; // LED 4

#define BASE "iot/luzambiente"
constexpr char TOPICO_COMANDO[] = BASE "/atuador/luz/comando";
constexpr char TOPICO_STATUS[] = BASE "/atuador/status"; // Novo tópico de confirmação
constexpr char DEVICE_ID[] = "atuador01";

char cenaAtual[16] = "apagada"; // Guarda o estado atual

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void desligarTodos() {
  digitalWrite(PIN_LED_AMBIENTE, LOW);
  digitalWrite(PIN_LED_ESCURO, LOW);
  digitalWrite(PIN_LED_ALTA, LOW);
  digitalWrite(PIN_LED_EXTREMA, LOW);
}

// EXIGÊNCIA DA N1: Função que fecha o ciclo comunicando a execução de volta
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

  desligarTodos(); // Limpa o estado anterior

  // Lógica de ativação baseada na cena
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
  
  // Publica a confirmação de que os LEDs mudaram fisicamente
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
    while (!mqtt.connect(DEVICE_ID)) { delay(1000); }
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