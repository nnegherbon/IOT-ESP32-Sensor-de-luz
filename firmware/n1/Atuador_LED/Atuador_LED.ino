/* NÓ ATUADOR — 4 Níveis de Luz (Com Confirmação de Estado para N1) */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#define WIFI_SSID "SUA_REDE"      // credencial removida do repositório (R9)
#define WIFI_PASSWORD "SUA_SENHA"  // credencial removida do repositório (R9)
#define MQTT_HOST "192.168.100.7"  // IP do PC com o Docker (broker Mosquitto local)
#define MQTT_PORT 1883

// Definição dos pinos saudáveis
constexpr uint8_t PIN_LED_ESCURO   = 27; // LED 1 (escuro)
constexpr uint8_t PIN_LED_AMBIENTE = 26; // LED 2 (ambiente)
constexpr uint8_t PIN_LED_ALTA     = 25; // LED 3
constexpr uint8_t PIN_LED_EXTREMA  = 33; // LED 4

// Servo da sombra (N3). Alimentado pelo USB (VIN), sem fonte externa:
// o movimento é suave (em passos) e o PWM é DESLIGADO logo após cada movimento.
// Nunca deixe o servo segurando posição continuamente: travado, ele aquece e queima
// (foi o que queimou o SG90 em 2026-11-22, parado em 0° = pulso de 500 µs, a ponta extrema).
constexpr uint8_t PIN_SERVO        = 18;
// Limites de segurança: nenhum ângulo fora desta faixa chega ao servo (folga dos batentes internos).
constexpr int SERVO_MIN_GRAUS      = 15;
constexpr int SERVO_MAX_GRAUS      = 165;
// Ângulos da sombra. Calibre com firmware/testes/Teste_Servo antes de gravar este sketch:
// encaixe o braço para que ABERTA fique na vertical e FECHADA na horizontal sobre a planta.
constexpr int SOMBRA_ABERTA_GRAUS  = 15;  // posição padrão: braço na vertical (planta recebe luz)
constexpr int SOMBRA_FECHADA_GRAUS = 120; // braço na horizontal sobre a planta
constexpr int PASSO_GRAUS          = 2;   // graus por passo do movimento suave
constexpr int PAUSA_PASSO_MS       = 30;  // pausa entre passos
constexpr int ESPERA_FINAL_MS      = 400; // tempo para o servo terminar o último passo antes de soltar
constexpr int ESPERA_BOOT_MS       = 1000; // no boot a posição real é desconhecida: dá tempo de percorrer tudo
constexpr bool FECHAR_EM_ALTA      = false; // true = fecha também na cena "alta"; false = só na "extrema"

#define BASE "iot/luzambiente"
constexpr char TOPICO_COMANDO[] = BASE "/atuador/luz/comando";
constexpr char TOPICO_STATUS[] = BASE "/atuador/status"; // Novo tópico de confirmação
constexpr char DEVICE_ID[] = "atuador01";
// Presença para a dashboard: "online" ao conectar e "offline" via LWT (ambos retidos)
constexpr char TOPICO_CONEXAO[] = BASE "/atuador/conexao";
constexpr char PAYLOAD_ONLINE[] = "{\"device\":\"atuador01\",\"status\":\"online\"}";
constexpr char PAYLOAD_OFFLINE[] = "{\"device\":\"atuador01\",\"status\":\"offline\"}";
// Posição da sombra para a dashboard (retido): {"device":"atuador01","estado":"aberta|fechada","graus":N}
// É a posição COMANDADA: o servo não informa a posição real.
constexpr char TOPICO_SOMBRA[] = BASE "/atuador/sombra";

char cenaAtual[16] = "apagada"; // Guarda o estado atual
int posicaoServo = SOMBRA_ABERTA_GRAUS; // Último ângulo enviado ao servo

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void desligarTodos() {
  digitalWrite(PIN_LED_AMBIENTE, LOW);
  digitalWrite(PIN_LED_ESCURO, LOW);
  digitalWrite(PIN_LED_ALTA, LOW);
  digitalWrite(PIN_LED_EXTREMA, LOW);
}

// Converte graus (0–180) no duty de 16 bits a 50 Hz (pulso de 500 a 2400 µs),
// sempre limitado à faixa segura SERVO_MIN_GRAUS..SERVO_MAX_GRAUS
void escreverServo(int graus) {
  graus = constrain(graus, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  uint32_t us = map(graus, 0, 180, 500, 2400);
  ledcWrite(PIN_SERVO, us * 65535 / 20000);
}

// Liga o PWM do servo. Retorna false se o LEDC falhar (aí o servo não é movido).
bool ligarServo() {
  if (!ledcAttach(PIN_SERVO, 50, 16)) {
    Serial.println("ERRO: nao foi possivel ligar o PWM do servo");
    return false;
  }
  return true;
}

// Solta o motor: sem pulsos o servo não faz força. O pino fica em LOW (e não flutuando),
// para que ruído no fio não seja lido como pulso e faça o servo tremer.
void soltarServo() {
  ledcDetach(PIN_SERVO);
  pinMode(PIN_SERVO, OUTPUT);
  digitalWrite(PIN_SERVO, LOW);
}

void publicarSombra() {
  char payload[96];
  snprintf(payload, sizeof(payload), "{\"device\":\"%s\",\"estado\":\"%s\",\"graus\":%d}", DEVICE_ID,
           posicaoServo == SOMBRA_FECHADA_GRAUS ? "fechada" : "aberta", posicaoServo);
  mqtt.publish(TOPICO_SOMBRA, payload, true);
}

// Move o servo devagar até o ângulo alvo e depois solta o motor (sem forçar em repouso)
void moverSombra(int alvo) {
  alvo = constrain(alvo, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  if (alvo == posicaoServo) return;
  if (!ligarServo()) return;
  int passo = (alvo > posicaoServo) ? PASSO_GRAUS : -PASSO_GRAUS;
  for (int g = posicaoServo; (passo > 0) ? (g < alvo) : (g > alvo); g += passo) {
    escreverServo(g);
    delay(PAUSA_PASSO_MS);
  }
  escreverServo(alvo);
  delay(ESPERA_FINAL_MS);
  soltarServo();
  posicaoServo = alvo;
  Serial.printf("Sombra %s (%d graus)\n", alvo == SOMBRA_FECHADA_GRAUS ? "FECHADA" : "ABERTA", alvo);
  publicarSombra();
}

bool cenaFechaSombra(const char* cena) {
  if (strcmp(cena, "extrema") == 0) return true;
  return FECHAR_EM_ALTA && strcmp(cena, "alta") == 0;
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
  // Atualiza os LEDs e confirma ANTES de mover o servo: o movimento leva ~2 s e não
  // deve atrasar a confirmação (a latência medida na dashboard é a dos LEDs).

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

  // N3: a cena extrema (e a alta, se FECHAR_EM_ALTA) fecha a sombra; as demais abrem
  moverSombra(cenaFechaSombra(cenaAtual) ? SOMBRA_FECHADA_GRAUS : SOMBRA_ABERTA_GRAUS);
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("WiFi");
    unsigned long inicio = millis();
    while (WiFi.status() != WL_CONNECTED) {
      delay(300); Serial.print(".");
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
    while (!mqtt.connect(DEVICE_ID, TOPICO_CONEXAO, 1, true, PAYLOAD_OFFLINE)) {
      if (WiFi.status() != WL_CONNECTED) return;  // Wi-Fi caiu: o próximo loop reconecta
      delay(1000);
    }
    mqtt.publish(TOPICO_CONEXAO, PAYLOAD_ONLINE, true);
    publicarSombra();
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

  // Começa com a sombra aberta (posição padrão) e solta o motor.
  // A posição real no boot é desconhecida, então o servo vai direto (sem passos): espera o
  // suficiente para ele completar o trajeto. Antes eram 500 ms e o braço às vezes parava no meio.
  if (ligarServo()) {
    escreverServo(SOMBRA_ABERTA_GRAUS);
    delay(ESPERA_BOOT_MS);
    soltarServo();
  }
  posicaoServo = SOMBRA_ABERTA_GRAUS;

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
}

void loop() {
  conectar();
  mqtt.loop();
}