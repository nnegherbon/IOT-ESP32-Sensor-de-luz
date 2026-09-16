/*
 * VERSÃO STANDALONE — plano B para a entrega da N1, sem Wi-Fi.
 *
 * Um único ESP32 lê o LDR, decide e acende o LED. Serve como fallback caso a
 * rede do laboratório falhe no dia da apresentação (ver docs/RISCOS.md, R6).
 * O código está dividido nas MESMAS três camadas do sistema distribuído:
 *
 *   lerSensores()  -> vira o nó sensor (publica telemetria MQTT)
 *   decidir()      -> vira o backend (a regra sai daqui e vai para o Python)
 *   aplicarCena()  -> vira o nó atuador (assina comandos MQTT)
 *
 * A regra abaixo é a mesma de backend/app/automation.py, inclusive na
 * histerese — mantenha as duas em sincronia.
 *
 * PRESENÇA (PIR), SOM (MAX9814) e RGB (WS2812B): O CÓDIGO ESTÁ AQUI,
 * COMENTADO, em blocos marcados "PRESENCA:", "SOM:" e "RGB:". Reativar é
 * trocar `#if 0` por `#if 1` nesses blocos quando os componentes chegarem.
 *
 * Ligação da luz (ativa agora):
 *   LDR + resistor ~10 kΩ formando um divisor de tensão:
 *     3V3 -> LDR -> GPIO 34 -> resistor 10 kΩ -> GND
 *   LED (+) -> resistor ~220-330 Ω -> GPIO 13   LED (-) -> GND
 */

#include <Arduino.h>

// ---------------------------------------------------------------- hardware
constexpr uint8_t PIN_LDR = 34;  // ADC1 obrigatoriamente
constexpr uint8_t PIN_LED = 13;

#if 0  // PRESENCA: pino do PIR, ainda não montado
constexpr uint8_t PIN_PIR = 27;
#endif
#if 0  // SOM: pino do microfone, ainda não montado
constexpr uint8_t PIN_SOM = 32;
#endif
#if 0  // RGB: fita/anel WS2812B, ainda não montada
constexpr uint8_t PIN_LED_RGB = 13;
constexpr uint16_t NUM_LEDS = 12;
#endif

// ---------------------------------------------------------------- regra
constexpr float LIMIAR_LUZ = 40.0f;
constexpr float HISTERESE_LUZ = 8.0f;
constexpr float LIMIAR_MEDIO = 25.0f;   // som, hoje inerte
constexpr float LIMIAR_ALTO = 55.0f;
constexpr float HISTERESE_SOM = 6.0f;
constexpr uint8_t BRILHO_MAX = 120;
constexpr uint32_t CARENCIA_PRESENCA_MS = 120000UL;  // presença, hoje inerte

// Som desativado: a regra usa este valor fixo em vez de uma leitura real.
constexpr float SOM_VALOR_PADRAO = 0.0f;

// Amostragem da luz (LDR é bem mais estável que áudio, basta uma média simples)
constexpr uint8_t AMOSTRAS_LUZ = 8;

#if 0  // SOM: janela de amostragem e calibração
constexpr uint32_t JANELA_AMOSTRAGEM_MS = 50;
constexpr float PP_SILENCIO = 120.0f;
constexpr float PP_MAXIMO = 2600.0f;
constexpr float SUAVIZACAO = 0.35f;
#endif

enum FaixaSom { BAIXO, MEDIO, ALTO };

struct Cena {
  bool escuro;
  uint8_t brilho;
  const char* animacao;  // "off" | "estatica" | "respiracao" | "pulso"
  const char* nome;
};

bool escuroAtual = false;
FaixaSom faixaSomAtual = BAIXO;

#if 0  // PRESENCA
uint32_t ultimoMovimentoMs = 0;
bool jaHouveMovimento = false;
#endif
#if 0  // SOM
float nivelSuavizado = 0.0f;
#endif

Cena cenaAtual = {false, 0, "off", "apagada"};

// ======================================================== CAMADA 1: SENSORES

/* Luminosidade em %, maior = mais claro (mesma convenção do backend). */
float lerLuminosidade() {
  uint32_t soma = 0;
  for (uint8_t i = 0; i < AMOSTRAS_LUZ; i++) {
    soma += analogRead(PIN_LDR);
    delay(5);
  }
  return (static_cast<float>(soma) / AMOSTRAS_LUZ) * 100.0f / 4095.0f;
}

#if 0  // PRESENCA
bool lerMovimento() { return digitalRead(PIN_PIR) == HIGH; }

/* Ocupação != movimento: o PIR perde quem fica parado. */
bool ambienteOcupado(bool movimento) {
  if (movimento) {
    ultimoMovimentoMs = millis();
    jaHouveMovimento = true;
    return true;
  }
  if (!jaHouveMovimento) return false;
  return (millis() - ultimoMovimentoMs) <= CARENCIA_PRESENCA_MS;
}
#endif  // PRESENCA

#if 0  // SOM
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
#endif  // SOM

// ========================================================== CAMADA 2: REGRA

/* Schmitt trigger de duas zonas: zona morta entre o limiar e o limiar mais a
 * histerese mantém o estado anterior, para o LED não piscar com o LDR
 * oscilando perto do limite. Mesma lógica de automation.py::classificar_luz. */
bool classificarLuz(float nivelLuz, bool escuroAnterior) {
  if (nivelLuz < LIMIAR_LUZ) return true;
  if (nivelLuz > LIMIAR_LUZ + HISTERESE_LUZ) return false;
  return escuroAnterior;
}

/* Som: continua ativa (não é código de sensor) porque é a mesma lógica
 * testada em backend/app/automation.py::classificar_som — só não recebe
 * leitura real por enquanto (nivelSom vem fixo de SOM_VALOR_PADRAO). */
FaixaSom classificarSom(float nivel, FaixaSom atual) {
  if (atual == ALTO) {
    if (nivel < LIMIAR_ALTO - HISTERESE_SOM) atual = MEDIO;
    else return ALTO;
  }
  if (atual == MEDIO) {
    if (nivel >= LIMIAR_ALTO) return ALTO;
    if (nivel < LIMIAR_MEDIO - HISTERESE_SOM) return BAIXO;
    return MEDIO;
  }
  if (nivel >= LIMIAR_ALTO) return ALTO;
  if (nivel >= LIMIAR_MEDIO) return MEDIO;
  return BAIXO;
}

Cena decidir(bool ocupado, float nivelLuz, float nivelSom) {
  if (!ocupado) {
    return {escuroAtual, 0, "off", "apagada"};
  }
  escuroAtual = classificarLuz(nivelLuz, escuroAtual);
  if (!escuroAtual) {
    return {escuroAtual, 0, "off", "claro"};
  }
  faixaSomAtual = classificarSom(nivelSom, faixaSomAtual);
  switch (faixaSomAtual) {
    case BAIXO:
      return {escuroAtual, static_cast<uint8_t>(BRILHO_MAX / 4), "estatica", "suave"};
    case MEDIO:
      return {escuroAtual, static_cast<uint8_t>(BRILHO_MAX * 3 / 5), "respiracao", "media"};
    default:
      return {escuroAtual, BRILHO_MAX, "pulso", "festa"};
  }
}

// ======================================================== CAMADA 3: ATUAÇÃO

/* LED comum: só liga/desliga. Ver docs/MONTAGEM.md e o firmware do atuador
 * para a opção de PWM (brilho gradual) e para a versão RGB comentada. */
void aplicarCena(const Cena& cena) {
  digitalWrite(PIN_LED, cena.brilho > 0 ? HIGH : LOW);
}

#if 0
// =========================================================== RGB (WS2812B)
// Requer FastLED no platformio.ini quando reativado.
#include <FastLED.h>
CRGB leds[NUM_LEDS];

void aplicarCenaRgb(const Cena& cena) {
  if (cena.brilho == 0 || strcmp(cena.animacao, "off") == 0) {
    FastLED.setBrightness(0);
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();
    return;
  }
  uint8_t brilho = cena.brilho;
  if (strcmp(cena.animacao, "respiracao") == 0) {
    brilho = scale8(cena.brilho, beatsin8(20, 60, 255));
  } else if (strcmp(cena.animacao, "pulso") == 0) {
    brilho = scale8(cena.brilho, beatsin8(120, 120, 255));
  }
  fill_solid(leds, NUM_LEDS, CRGB(255, 170, 80));  // troque pela cor da cena quando integrar
  FastLED.setBrightness(brilho);
  FastLED.show();
}
#endif  // RGB

// =============================================================== ORQUESTRAÇÃO

uint32_t ultimaDecisao = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_LDR, ADC_11db);

#if 0  // PRESENCA
  pinMode(PIN_PIR, INPUT);
#endif
#if 0  // SOM
  analogSetPinAttenuation(PIN_SOM, ADC_11db);
#endif
#if 0  // RGB
  FastLED.addLeds<WS2812B, PIN_LED_RGB, GRB>(leds, NUM_LEDS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, 500);
  FastLED.clear(true);
#endif

#if 0  // PRESENCA: o HC-SR501 precisa de ~60 s estabilizando
  Serial.println("PIR aquecendo por 60 s — leituras iniciais nao valem.");
  delay(60000);
#endif
  Serial.println("pronto (presenca e som desativados). formato: luz | cena");
}

void loop() {
  if (millis() - ultimaDecisao >= 500) {
    ultimaDecisao = millis();
    const float luz = lerLuminosidade();
#if 0  // SOM
    const float som = lerNivelSom();
#else
    const float som = SOM_VALOR_PADRAO;
#endif
#if 0  // PRESENCA
    const bool ocupado = ambienteOcupado(lerMovimento());
#else
    const bool ocupado = true;  // sempre ocupado enquanto nao ha PIR
#endif
    cenaAtual = decidir(ocupado, luz, som);
    Serial.printf("%.1f%% | %s\n", luz, cenaAtual.nome);
  }
  aplicarCena(cenaAtual);
#if 0  // RGB
  aplicarCenaRgb(cenaAtual);
  FastLED.delay(16);
#else
  delay(16);
#endif
}
