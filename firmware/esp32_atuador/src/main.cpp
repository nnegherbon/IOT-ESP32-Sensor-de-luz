/*
 * Nó ATUADOR — Luz Ambiente Inteligente
 *
 * Assina os comandos de cena publicados pelo backend e aciona um LED comum.
 * Não conhece o sensor: só o contrato de mensagens. Depois de aplicar,
 * publica o estado confirmado (retido) — comando enviado não é prova de
 * comando aplicado.
 *
 * FITA/ANEL RGB (WS2812B): O CÓDIGO ESTÁ AQUI, COMENTADO.
 * A fita ainda não chegou. A versão em blocos `#if 0 ... #endif` marcados
 * "RGB:" faz o mesmo contrato (cena/brilho/cor/animação) só que numa fita
 * WS2812B via FastLED, em vez de um LED comum. Para reativar:
 *   1. Trocar os `#if 0` marcados "RGB:" por `#if 1`, e o bloco ativo
 *      "LED COMUM" por `#if 0`.
 *   2. Adicionar `fastled/FastLED@^3.9.13` de volta ao platformio.ini.
 *   3. Ligar o hardware conforme a nota de nível lógico no bloco RGB.
 *
 * Ligação do LED comum (ativa agora):
 *   LED (+) -> resistor ~220-330 Ω -> GPIO 13
 *   LED (-) -> GND
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include "secrets.h"

// ---------------------------------------------------------------- hardware
constexpr uint8_t PIN_LED = 13;

#if 0  // RGB: pino de dados da fita/anel WS2812B, ainda não montada
constexpr uint8_t PIN_LED_RGB = 13;
constexpr uint16_t NUM_LEDS = 12;
#endif

// ---------------------------------------------------------------- tópicos
#define BASE "iot/luzambiente"
constexpr char TOPICO_COMANDO[] = BASE "/atuador/luz/comando";
constexpr char TOPICO_STATUS[] = BASE "/atuador/status";
constexpr char TOPICO_CONEXAO[] = BASE "/atuador/conexao";
constexpr char DEVICE_ID[] = "atuador01";

// Estado aplicado localmente. O LED comum só entende "aceso ou apagado" (o
// campo brilho > 0 decide isso); cor e animação continuam guardados e
// confirmados no status, prontos para quando a fita RGB existir.
char cenaAtual[16] = "apagada";
char animacaoAtual[16] = "off";
uint8_t brilhoAlvo = 0;
uint8_t corR = 0, corG = 0, corB = 0;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void publicarStatus() {
  char payload[160];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"cena\":\"%s\",\"brilho\":%u,"
           "\"cor\":{\"r\":%u,\"g\":%u,\"b\":%u},\"animacao\":\"%s\"}",
           DEVICE_ID, cenaAtual, brilhoAlvo, corR, corG, corB, animacaoAtual);
  mqtt.publish(TOPICO_STATUS, payload, true);
}

void onMessage(char* topic, byte* bytes, unsigned int length) {
  JsonDocument doc;
  if (deserializeJson(doc, bytes, length)) {
    Serial.println("comando com JSON invalido, ignorado");
    return;
  }

  strlcpy(cenaAtual, doc["cena"] | "manual", sizeof(cenaAtual));
  strlcpy(animacaoAtual, doc["animacao"] | "estatica", sizeof(animacaoAtual));
  brilhoAlvo = constrain(static_cast<int>(doc["brilho"] | 0), 0, 255);
  corR = doc["cor"]["r"] | 0;
  corG = doc["cor"]["g"] | 0;
  corB = doc["cor"]["b"] | 0;

  Serial.printf("cena=%s brilho=%u anim=%s (LED comum ignora cor)\n",
                cenaAtual, brilhoAlvo, animacaoAtual);
  publicarStatus();
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("wifi");
    while (WiFi.status() != WL_CONNECTED) {
      delay(300);
      Serial.print(".");
    }
    Serial.printf(" ok, ip=%s\n", WiFi.localIP().toString().c_str());
  }
  if (!mqtt.connected()) {
    while (!mqtt.connect(DEVICE_ID, TOPICO_CONEXAO, 1, true, "offline")) {
      Serial.println("mqtt falhou, tentando de novo");
      delay(1000);
    }
    mqtt.subscribe(TOPICO_COMANDO, 1);
    mqtt.publish(TOPICO_CONEXAO, "online", true);
    publicarStatus();
    Serial.println("mqtt ok");
  }
}

// ======================================================= LED COMUM (ativo)

/* Liga se o brilho pedido for > 0 e a animação não for "off". Um LED comum
 * não faz gradiente de verdade sem PWM; on/off já é suficiente para validar
 * o ciclo completo (sensor -> backend -> atuador) com o hardware atual. */
void aplicarLedComum() {
  const bool aceso = brilhoAlvo > 0 && strcmp(animacaoAtual, "off") != 0;
  digitalWrite(PIN_LED, aceso ? HIGH : LOW);
}

#if 0
// ---------------------------------------------------- BRILHO EM PWM (extra)
// Alternativa opcional ao on/off acima: brilho proporcional via PWM, sem
// precisar de fita RGB. Puxa esta versão quando quiserem mostrar intensidade
// gradual num LED comum. Requer o núcleo Arduino-ESP32 3.x (API ledc nova).
void aplicarLedComumPwm() {
  const uint32_t canal = 0;
  ledcAttach(PIN_LED, 5000, 8);  // 5 kHz, 8 bits
  uint8_t brilho = brilhoAlvo;
  if (strcmp(animacaoAtual, "respiracao") == 0) {
    const float fase = (millis() % 3000) / 3000.0f;
    brilho = static_cast<uint8_t>(brilhoAlvo * (0.5f + 0.5f * sinf(fase * 2 * PI)));
  } else if (strcmp(animacaoAtual, "off") == 0) {
    brilho = 0;
  }
  ledcWrite(PIN_LED, brilho);
}
#endif

#if 0
// =========================================================== RGB (WS2812B)
// Versão completa para quando a fita/anel chegar. Requer FastLED no
// platformio.ini (fastled/FastLED@^3.9.13) e nível lógico resolvido — ver
// nota abaixo.
//
// NOTA DE NÍVEL LÓGICO: o WS2812B espera ~3,5 V no DIN e o ESP32 entrega
// 3,3 V. Costuma funcionar, mas é a causa clássica do "ontem funcionava".
// Se aparecer LED fantasma ou cor errada: level shifter (74AHCT125) ou
// alimentar a fita com ~4,5 V.
#include <FastLED.h>
CRGB leds[NUM_LEDS];

void aplicarLedsRgb() {
  uint8_t brilho = brilhoAlvo;
  if (strcmp(animacaoAtual, "off") == 0 || brilhoAlvo == 0) {
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.setBrightness(0);
    FastLED.show();
    return;
  }
  if (strcmp(animacaoAtual, "respiracao") == 0) {
    brilho = scale8(brilhoAlvo, beatsin8(20, 60, 255));
  } else if (strcmp(animacaoAtual, "pulso") == 0) {
    brilho = scale8(brilhoAlvo, beatsin8(120, 120, 255));
  }
  fill_solid(leds, NUM_LEDS, CRGB(corR, corG, corB));
  FastLED.setBrightness(brilho);
  FastLED.show();
}
#endif  // RGB

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

#if 0  // RGB: inicialização da fita
  FastLED.addLeds<WS2812B, PIN_LED_RGB, GRB>(leds, NUM_LEDS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, 500);
  FastLED.setBrightness(0);
  FastLED.clear(true);
#endif

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setBufferSize(512);
  conectar();
}

void loop() {
  conectar();
  mqtt.loop();
  aplicarLedComum();
#if 0  // RGB: renderizar a fita a cada quadro, no lugar do LED comum acima
  aplicarLedsRgb();
  FastLED.delay(16);
#endif
}
