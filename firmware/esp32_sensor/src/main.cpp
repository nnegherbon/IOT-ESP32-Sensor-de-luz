/*
 * Nó SENSOR — Luz Ambiente Inteligente
 *
 * Lê luminosidade (LDR) e publica como telemetria MQTT. Este nó NÃO decide
 * nada sobre a iluminação: quem decide é o backend. É o único sensor físico
 * montado até agora — presença (PIR) e som (MAX9814) ainda não chegaram.
 *
 * PRESENÇA (PIR) e SOM (MAX9814): O CÓDIGO ESTÁ AQUI, COMENTADO.
 * Ficam em blocos `#if 0 ... #endif` marcados "PRESENCA:" e "SOM:", para não
 * perder o trabalho já feito. Para reativar cada um, quando o componente
 * chegar:
 *   1. Trocar os `#if 0` daquele bloco por `#if 1`.
 *   2. Ligar o hardware conforme a pinagem dentro do bloco.
 *   3. No backend: OCUPACAO_HABILITADA=true (PIR) ou SOM_HABILITADO=true (som).
 *
 * Ligação da luz (ativa agora):
 *   LDR + resistor ~10 kΩ formando um divisor de tensão:
 *     3V3 -> LDR -> GPIO 34 -> resistor 10 kΩ -> GND
 *   Confirmem o valor do resistor no divisor montado — ver docs/MONTAGEM.md.
 *
 * NOTA SOBRE O ADC: o ADC2 do ESP32 é usado pelo rádio Wi-Fi e devolve lixo
 * (ou trava) quando o Wi-Fi está ligado. Use somente pinos do ADC1:
 * 32, 33, 34, 35, 36, 39.
 */

#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include "secrets.h"

// ---------------------------------------------------------------- hardware
constexpr uint8_t PIN_LDR = 34;  // ADC1_CH6

#if 0  // PRESENCA: pino do PIR HC-SR501, ainda não montado
constexpr uint8_t PIN_PIR = 27;
#endif

#if 0  // SOM: pino do microfone MAX9814, ainda não montado (use outro ADC1 livre)
constexpr uint8_t PIN_SOM = 32;
#endif

// ---------------------------------------------------------------- tópicos
#define BASE "iot/luzambiente"
constexpr char TOPICO_LUZ[] = BASE "/sensor/luminosidade";
constexpr char TOPICO_STATUS[] = BASE "/sensor/status";
constexpr char DEVICE_ID[] = "sensor01";

#if 0  // PRESENCA: tópico de telemetria de movimento
constexpr char TOPICO_PRESENCA[] = BASE "/sensor/presenca";
#endif

#if 0  // SOM: tópico de telemetria de som
constexpr char TOPICO_SOM[] = BASE "/sensor/som";
#endif

// ---------------------------------------------------------------- tempos
constexpr uint32_t INTERVALO_LUZ_MS = 2000;    // telemetria de luminosidade
constexpr uint8_t AMOSTRAS_LUZ = 8;            // média simples, LDR é bem menos ruidoso que áudio

#if 0  // PRESENCA
constexpr uint32_t HEARTBEAT_PRESENCA_MS = 15000;  // reenvio periódico
#endif

#if 0  // SOM: janela de amostragem e calibração (ver docs/CALIBRACAO.md)
constexpr uint32_t JANELA_AMOSTRAGEM_MS = 50;
constexpr uint32_t INTERVALO_SOM_MS = 500;
constexpr float PP_SILENCIO = 120.0f;
constexpr float PP_MAXIMO = 2600.0f;
constexpr float SUAVIZACAO = 0.35f;
#endif

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

uint32_t ultimoEnvioLuz = 0;

#if 0  // PRESENCA
bool movimentoAnterior = false;
uint32_t ultimoEnvioPresenca = 0;
#endif

#if 0  // SOM
float nivelSuavizado = 0.0f;
uint32_t ultimoEnvioSom = 0;
#endif

/*
 * Lê a luminosidade em %, onde valor MAIOR significa AMBIENTE MAIS CLARO
 * (convenção usada em todo o projeto — ver backend/app/automation.py).
 * Depende do divisor de tensão estar montado com o LDR do lado de 3V3: nessa
 * configuração, mais luz -> menor resistência do LDR -> mais tensão no ponto
 * médio -> leitura do ADC maior.
 *
 * O LDR é bem mais estável que um microfone, então uma média simples de
 * poucas amostras já resolve — não precisa de pico a pico como no som.
 */
float lerLuminosidade() {
  uint32_t soma = 0;
  for (uint8_t i = 0; i < AMOSTRAS_LUZ; i++) {
    soma += analogRead(PIN_LDR);
    delay(5);
  }
  const float media = static_cast<float>(soma) / AMOSTRAS_LUZ;
  return media * 100.0f / 4095.0f;
}

#if 0
/*
 * Lê a envoltória do som (pico a pico numa janela, não uma amostra isolada).
 * Um analogRead() isolado não serve: o MAX9814 entrega uma ONDA centrada em
 * ~1,25 V, então uma leitura única cai num ponto aleatório da senoide.
 */
float lerNivelSom() {
  uint16_t minimo = 4095, maximo = 0;
  const uint32_t fim = millis() + JANELA_AMOSTRAGEM_MS;
  while (millis() < fim) {
    const uint16_t amostra = analogRead(PIN_SOM);
    if (amostra < minimo) minimo = amostra;
    if (amostra > maximo) maximo = amostra;
  }
  float pct = (static_cast<float>(maximo - minimo) - PP_SILENCIO) * 100.0f /
              (PP_MAXIMO - PP_SILENCIO);
  pct = constrain(pct, 0.0f, 100.0f);
  nivelSuavizado = SUAVIZACAO * pct + (1.0f - SUAVIZACAO) * nivelSuavizado;
  return nivelSuavizado;
}
#endif  // SOM: lerNivelSom()

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
    // LWT: se este nó cair sem avisar, o broker publica "offline" sozinho.
    while (!mqtt.connect(DEVICE_ID, TOPICO_STATUS, 1, true, "offline")) {
      Serial.println("mqtt falhou, tentando de novo");
      delay(1000);
    }
    mqtt.publish(TOPICO_STATUS, "online", true);
    Serial.println("mqtt ok");
  }
}

void publicarLuz(float nivel) {
  char payload[110];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"value\":%.1f,\"unit\":\"%%\"}", DEVICE_ID, nivel);
  mqtt.publish(TOPICO_LUZ, payload, false);
}

#if 0  // PRESENCA: publicação da telemetria de movimento
void publicarPresenca(bool movimento) {
  char payload[96];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"movimento\":%s}", DEVICE_ID,
           movimento ? "true" : "false");
  mqtt.publish(TOPICO_PRESENCA, payload, false);
}
#endif

#if 0  // SOM: publicação da telemetria de som
void publicarSom(float nivel) {
  char payload[110];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"value\":%.1f,\"unit\":\"%%\"}", DEVICE_ID, nivel);
  mqtt.publish(TOPICO_SOM, payload, false);
}
#endif

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_LDR, ADC_11db);  // abre a faixa de entrada para 0-3,3 V

#if 0  // PRESENCA
  pinMode(PIN_PIR, INPUT);
#endif
#if 0  // SOM
  analogSetPinAttenuation(PIN_SOM, ADC_11db);
#endif

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  conectar();

#if 0  // PRESENCA: o HC-SR501 precisa de ~60 s estabilizando depois de energizar
  Serial.println("PIR aquecendo por 60 s — leituras iniciais nao valem.");
  delay(60000);
#endif
  Serial.println("sensor pronto (presenca e som desativados nesta versao).");
}

void loop() {
  conectar();
  mqtt.loop();

  const uint32_t agora = millis();

  if (agora - ultimoEnvioLuz >= INTERVALO_LUZ_MS) {
    ultimoEnvioLuz = agora;
    const float luz = lerLuminosidade();
    publicarLuz(luz);
    Serial.printf("luz: %.1f%%\n", luz);
  }

#if 0  // PRESENCA: leitura e publicação por mudança de estado
  const bool movimento = digitalRead(PIN_PIR) == HIGH;
  if (movimento != movimentoAnterior || agora - ultimoEnvioPresenca > HEARTBEAT_PRESENCA_MS) {
    movimentoAnterior = movimento;
    ultimoEnvioPresenca = agora;
    publicarPresenca(movimento);
    Serial.printf("presenca: %s\n", movimento ? "movimento" : "parado");
  }
#endif

#if 0  // SOM: leitura e publicação periódica
  if (agora - ultimoEnvioSom >= INTERVALO_SOM_MS) {
    ultimoEnvioSom = agora;
    const float nivel = lerNivelSom();
    publicarSom(nivel);
    Serial.printf("som: %.1f%%\n", nivel);
  }
#endif
}
