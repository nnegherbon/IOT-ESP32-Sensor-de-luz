/* TESTE DO SERVO DA SOMBRA — sem Wi-Fi, sem MQTT
 *
 * Serve para testar um servo novo e calibrar os ângulos antes de gravar o Atuador_LED.
 * Usa o MESMO movimento do firmware real: passos suaves e PWM desligado no fim.
 *
 * Ligação (igual ao atuador): sinal no GPIO18 (D18), + no VIN, − no GND.
 * Monitor Serial a 115200, com "Nova linha" no final. Comandos:
 *   a        → vai para a posição ABERTA
 *   f        → vai para a posição FECHADA
 *   v        → vai e volta 3x entre ABERTA e FECHADA
 *   número   → vai para esse ângulo (ex.: 45), limitado a 15..165
 *   p        → mostra a posição atual
 *
 * PARE NA HORA (tire o USB) se o servo zumbir sem girar, esquentar ou cheirar a queimado.
 * Encontrados os ângulos certos, copie-os para SOMBRA_ABERTA_GRAUS / SOMBRA_FECHADA_GRAUS
 * em firmware/n1/Atuador_LED/Atuador_LED.ino.
 */
#include <Arduino.h>

constexpr uint8_t PIN_SERVO        = 18;
constexpr int SERVO_MIN_GRAUS      = 15;
constexpr int SERVO_MAX_GRAUS      = 165;
constexpr int SOMBRA_ABERTA_GRAUS  = 15;
constexpr int SOMBRA_FECHADA_GRAUS = 90; 
constexpr int PASSO_GRAUS          = 2;
constexpr int PAUSA_PASSO_MS       = 30;
constexpr int ESPERA_FINAL_MS      = 400;
constexpr int ESPERA_BOOT_MS       = 1000;

int posicao = SOMBRA_ABERTA_GRAUS;
bool servoOk = false; // PWM ligado uma vez no setup e nunca desligado

void escreverServo(int graus) {
  graus = constrain(graus, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  uint32_t us = map(graus, 0, 180, 500, 2400);
  ledcWrite(PIN_SERVO, us * 65535 / 20000);
}

bool ligarServo() {
  if (!ledcAttach(PIN_SERVO, 50, 16)) {
    Serial.println("ERRO: nao foi possivel ligar o PWM do servo");
    return false;
  }
  return true;
}

// Solta o motor: duty 0 = pino em LOW, sem pulsos, e o servo não faz força.
// O PWM continua ligado: ledcDetach + ledcAttach de novo deixava o pino sem sinal
// (o servo só mexia no primeiro movimento, no boot).
void soltarServo() {
  ledcWrite(PIN_SERVO, 0);
}

void mover(int alvo) {
  alvo = constrain(alvo, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  if (alvo == posicao) { Serial.printf("Ja esta em %d graus\n", posicao); return; }
  if (!servoOk) { Serial.println("ERRO: PWM do servo nao inicializado"); return; }
  unsigned long t0 = millis();
  int passo = (alvo > posicao) ? PASSO_GRAUS : -PASSO_GRAUS;
  for (int g = posicao; (passo > 0) ? (g < alvo) : (g > alvo); g += passo) {
    escreverServo(g);
    delay(PAUSA_PASSO_MS);
  }
  escreverServo(alvo);
  delay(ESPERA_FINAL_MS);
  soltarServo();
  Serial.printf("%d -> %d graus em %lu ms (motor solto)\n", posicao, alvo, millis() - t0);
  posicao = alvo;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nTeste do servo. Indo para ABERTA...");
  servoOk = ligarServo();
  if (servoOk) {
    escreverServo(SOMBRA_ABERTA_GRAUS);
    delay(ESPERA_BOOT_MS);
    soltarServo();
  }
  posicao = SOMBRA_ABERTA_GRAUS;
  Serial.printf("Pronto em %d graus. Comandos: a, f, v, p ou um angulo (%d..%d)\n",
                posicao, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
}

void loop() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.isEmpty()) return;
  if (cmd == "a") mover(SOMBRA_ABERTA_GRAUS);
  else if (cmd == "f") mover(SOMBRA_FECHADA_GRAUS);
  else if (cmd == "p") Serial.printf("Posicao: %d graus\n", posicao);
  else if (cmd == "t") {
    // Diagnóstico do pino: TIRE o fio de sinal do servo e ligue um LED com 330 ohms
    // do D18 ao GND. O LED deve piscar 5x. (Nível alto contínuo não é pulso de servo.)
    Serial.println("Teste do pino D18: o LED deve piscar 5x");
    for (int i = 0; i < 5; i++) {
      ledcWrite(PIN_SERVO, 65535); delay(500);
      ledcWrite(PIN_SERVO, 0);     delay(500);
    }
    Serial.println("Fim do teste do pino");
  }
  else if (cmd == "v") {
    for (int i = 0; i < 3; i++) {
      mover(SOMBRA_FECHADA_GRAUS); delay(1000);
      mover(SOMBRA_ABERTA_GRAUS);  delay(1000);
    }
  } else if (isDigit(cmd[0])) mover(cmd.toInt());
  else Serial.println("Comando desconhecido. Use a, f, v, p ou um angulo.");
}
