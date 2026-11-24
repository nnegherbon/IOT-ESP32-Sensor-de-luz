/* LUZ AMBIENTE · NÓ ATUADOR (atuador01) · contrato MQTT v1.1
 *
 * Recebe comandos SÓ do backend (luzambiente/v1/atuador/atuador01/comando), executa e responde:
 *   ack "recebido" -> executa (LEDs + sombra) -> ack "executado" | "rejeitado" + motivo -> estado retido.
 * Modos: AUTO (aceita origem auto) · MANUAL (aceita origem manual, volta a AUTO no timeout) · SEGURO.
 * SEGURO (regra local, funciona sem rede): MQTT caído > seguro_apos_s, backend ou sensor offline (LWT).
 *   LEDs de cena apagados, LED 1 pisca a 1 Hz, servo SEM PWM (a sombra fica onde está), comandos rejeitados.
 *   Justificativa: sem o backend o atuador não sabe a luz real; não mexer no servo é o que não piora a planta
 *   e protege o próprio servo (o SG90 anterior queimou travado).
 * Intertravamento: 5 s entre movimentos do servo. cmd_id repetido: reenvia o ack original e não executa de novo.
 * Laço não bloqueante: o servo anda em passos por millis(), sem delay() no loop.
 * Configuração persistente (NVS): seguro_apos_s, sombra_fechada_graus, Wi-Fi e broker (via Serial ou MQTT).
 * OTA: ArduinoOTA (hostname atuador01, senha em secrets.h).
 * Credenciais: secrets.h (fora do Git). Modelo: secrets.example.h.
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include "secrets.h"

#define FW_VERSION "3.0.0"
static const char* DEVICE = "atuador01";

// ---------------------------------------------------------------- pinos
constexpr uint8_t PIN_LED[4] = {27, 26, 25, 33};  // LED1 escuro · LED2 ambiente · LED3 alta · LED4 extrema
constexpr uint8_t PIN_SERVO = 18;
// Servo: faixa segura e movimento suave (o SG90 anterior queimou segurando a ponta com PWM ligado)
constexpr int SERVO_MIN_GRAUS = 15, SERVO_MAX_GRAUS = 165;
constexpr int SOMBRA_ABERTA_GRAUS = 15;
constexpr int PASSO_GRAUS = 2;
constexpr uint32_t PAUSA_PASSO_MS = 30, ESPERA_FINAL_MS = 400, INTERTRAVAMENTO_MS = 5000;

// ---------------------------------------------------------------- tópicos
#define BASE "luzambiente/v1/atuador/atuador01/"
static const char* T_STATUS = BASE "status";
static const char* T_COMANDO = BASE "comando";
static const char* T_ACK = BASE "ack";
static const char* T_ESTADO = BASE "estado";
static const char* T_CONFIG = BASE "config";
static const char* T_BACKEND = "luzambiente/v1/backend/status";
static const char* T_SENSOR = "luzambiente/v1/sensor/+/status";

// ---------------------------------------------------------------- configuração persistente
Preferences prefs;
String cfgSsid, cfgPass, cfgHost;
uint32_t cfgSeguroAposS = 30;
int cfgSombraFechada = 90;

// ---------------------------------------------------------------- estado
enum Modo { AUTO, MANUAL, SEGURO };
Modo modo = SEGURO;                 // no boot: seguro até o backend e o sensor aparecerem
String motivoSeguro = "boot";
int cenaIdx = -1;                   // -1 = nenhuma
bool leds[4] = {false, false, false, false};
int sombra = -1;                    // -1 desconhecida · 0 aberta · 1 fechada
int servoAtual = SOMBRA_ABERTA_GRAUS, servoAlvo = SOMBRA_ABERTA_GRAUS;
bool servoMovendo = false, servoOk = false;
uint32_t ultimoPasso = 0, fimMovimento = 0, ultimoMovimento = 0;
String cmdEmExecucao;               // ack "executado" sai quando o servo termina
uint32_t manualAte = 0;
String ultimoCmdId;
bool backendOnline = false, sensorOnline = false;
uint32_t mqttCaiuEm = 0, ultimoEstado = 0, ultimaTentativaWifi = 0, ultimaTentativaMqtt = 0;
uint32_t wifiPausadoAte = 0;        // teste de falha: "wifioff N" pelo Serial

static const char* CENAS[4] = {"escuro", "ambiente", "alta", "extrema"};

struct AckGuardado { String cmdId; String resultado; String motivo; };
AckGuardado historico[8];
uint8_t historicoPos = 0;

WiFiClient net;
PubSubClient mqtt(net);

void logf(const char* fmt, ...) {
  char buf[200];
  va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);
  Serial.printf("[%8lu] %s\n", (unsigned long)millis(), buf);
}

const char* nomeModo() { return modo == AUTO ? "auto" : modo == MANUAL ? "manual" : "seguro"; }

// ---------------------------------------------------------------- NVS
void carregarConfig() {
  prefs.begin("cfg", true);
  cfgSsid = prefs.getString("ssid", WIFI_SSID);
  cfgPass = prefs.getString("pass", WIFI_PASS);
  cfgHost = prefs.getString("host", MQTT_HOST);
  cfgSeguroAposS = prefs.getUInt("seguro_s", 30);
  cfgSombraFechada = prefs.getInt("fechada", 90);
  prefs.end();
  logf("config: wifi=%s host=%s seguro_apos_s=%u sombra_fechada=%d", cfgSsid.c_str(), cfgHost.c_str(),
       (unsigned)cfgSeguroAposS, cfgSombraFechada);
}

void salvar(const char* chave, const String& v) { prefs.begin("cfg", false); prefs.putString(chave, v); prefs.end(); }
void salvarU(const char* chave, uint32_t v) { prefs.begin("cfg", false); prefs.putUInt(chave, v); prefs.end(); }
void salvarI(const char* chave, int v) { prefs.begin("cfg", false); prefs.putInt(chave, v); prefs.end(); }

// ---------------------------------------------------------------- saídas
void escreverServo(int graus) {
  graus = constrain(graus, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  uint32_t us = map(graus, 0, 180, 500, 2400);
  ledcWrite(PIN_SERVO, us * 65535 / 20000);
}
void soltarServo() { ledcWrite(PIN_SERVO, 0); }   // duty 0: sem pulsos, o servo não faz força

void aplicarLeds(int idx) {
  for (int i = 0; i < 4; i++) leds[i] = (idx == 3) || (i == idx);
  if (idx < 0) for (int i = 0; i < 4; i++) leds[i] = false;
  for (int i = 0; i < 4; i++) digitalWrite(PIN_LED[i], leds[i] ? HIGH : LOW);
}

void iniciarMovimento(int alvo) {
  alvo = constrain(alvo, SERVO_MIN_GRAUS, SERVO_MAX_GRAUS);
  if (!servoOk) { logf("ERRO: PWM do servo indisponível"); return; }
  servoAlvo = alvo;
  servoMovendo = true;
  ultimoPasso = 0;
  fimMovimento = 0;
}

// Um passo por chamada (sem delay): o loop continua atendendo MQTT, OTA e Serial
void cuidarServo() {
  if (!servoMovendo) return;
  uint32_t agora = millis();
  if (servoAtual != servoAlvo) {
    if (agora - ultimoPasso < PAUSA_PASSO_MS) return;
    ultimoPasso = agora;
    int passo = servoAlvo > servoAtual ? PASSO_GRAUS : -PASSO_GRAUS;
    servoAtual = abs(servoAlvo - servoAtual) <= PASSO_GRAUS ? servoAlvo : servoAtual + passo;
    escreverServo(servoAtual);
    if (servoAtual == servoAlvo) fimMovimento = agora;
    return;
  }
  if (agora - fimMovimento < ESPERA_FINAL_MS) return;
  soltarServo();
  servoMovendo = false;
  ultimoMovimento = agora;
  logf("sombra %s (%d graus, motor solto)", sombra == 1 ? "FECHADA" : "ABERTA", servoAtual);
  if (cmdEmExecucao.length()) {
    publicarAck(cmdEmExecucao, "executado", nullptr);
    guardarAck(cmdEmExecucao, "executado", "");
    cmdEmExecucao = "";
  }
  publicarEstado();
}

// ---------------------------------------------------------------- MQTT: publicação
void publicarAck(const String& cmdId, const char* resultado, const char* motivo) {
  JsonDocument d;
  d["v"] = 1; d["device"] = DEVICE; d["cmd_id"] = cmdId; d["resultado"] = resultado;
  if (motivo && *motivo) d["motivo"] = motivo; else d["motivo"] = nullptr;
  d["uptime_ms"] = millis();
  char buf[256]; size_t n = serializeJson(d, buf);
  mqtt.publish(T_ACK, (const uint8_t*)buf, n, false);
  logf("ack %s %s%s%s", cmdId.c_str(), resultado, motivo && *motivo ? " motivo=" : "", motivo ? motivo : "");
}

void publicarEstado() {
  JsonDocument d;
  d["v"] = 1; d["device"] = DEVICE; d["modo"] = nomeModo();
  if (cenaIdx >= 0) d["cena"] = CENAS[cenaIdx]; else d["cena"] = nullptr;
  JsonArray l = d["leds"].to<JsonArray>();
  for (int i = 0; i < 4; i++) l.add(modo == SEGURO ? false : leds[i]);
  if (sombra < 0) { d["sombra"] = nullptr; d["servo_graus"] = nullptr; }
  else { d["sombra"] = sombra ? "fechada" : "aberta"; d["servo_graus"] = sombra ? 90 : 0; d["angulo_real"] = servoAtual; }
  if (modo == MANUAL) d["manual_restante_s"] = (manualAte - millis()) / 1000; else d["manual_restante_s"] = nullptr;
  if (ultimoCmdId.length()) d["ultimo_cmd_id"] = ultimoCmdId; else d["ultimo_cmd_id"] = nullptr;
  d["uptime_ms"] = millis();
  if (modo == SEGURO) d["motivo_seguro"] = motivoSeguro;
  char buf[400]; size_t n = serializeJson(d, buf);
  if (mqtt.connected()) mqtt.publish(T_ESTADO, (const uint8_t*)buf, n, true);
  ultimoEstado = millis();
}

void guardarAck(const String& id, const char* res, const char* mot) {
  historico[historicoPos] = {id, res, mot ? mot : ""};
  historicoPos = (historicoPos + 1) % 8;
}

int buscarHistorico(const String& id) {
  for (int i = 0; i < 8; i++) if (historico[i].cmdId == id) return i;
  return -1;
}

// ---------------------------------------------------------------- modos
void entrarSeguro(const char* motivo) {
  if (modo == SEGURO) return;
  modo = SEGURO;
  motivoSeguro = motivo;
  cenaIdx = -1;
  aplicarLeds(-1);
  if (servoMovendo) { servoAlvo = servoAtual; }  // para onde está
  soltarServo();
  logf("MODO SEGURO: %s", motivo);
  publicarEstado();
}

void sairSeguroSePuder() {
  if (modo != SEGURO) return;
  if (mqtt.connected() && backendOnline && sensorOnline) {
    modo = AUTO;
    aplicarLeds(-1);
    logf("condições normalizadas: modo AUTO (aguardando comando do backend)");
    publicarEstado();
  }
}

// ---------------------------------------------------------------- comandos
int idxCena(const char* c) {
  for (int i = 0; i < 4; i++) if (c && strcmp(c, CENAS[i]) == 0) return i;
  return -1;
}

void processarComando(byte* payload, unsigned int len) {
  JsonDocument d;
  DeserializationError err = deserializeJson(d, payload, len);
  String cmdId = (!err && d["cmd_id"].is<const char*>()) ? String((const char*)d["cmd_id"]) : String("");
  bool idOk = cmdId.length() == 17 && cmdId.startsWith("c-");
  if (err || !idOk) {
    logf("comando descartado: %s", err ? err.c_str() : "cmd_id ausente ou inválido");
    if (idOk) publicarAck(cmdId, "rejeitado", "payload_invalido");
    return;
  }
  // Idempotência: cmd_id já processado -> reenvia o ack original, não executa de novo
  int h = buscarHistorico(cmdId);
  if (h >= 0 || cmdId == cmdEmExecucao) {
    logf("cmd_id repetido %s: reenviando ack original sem executar", cmdId.c_str());
    if (h >= 0) publicarAck(cmdId, historico[h].resultado.c_str(), historico[h].motivo.c_str());
    return;
  }
  publicarAck(cmdId, "recebido", nullptr);

  const char* origem = d["origem"] | "";
  const char* acao = d["acao"] | "";
  const char* motivo = nullptr;
  if (d["v"] != 1 || (strcmp(origem, "auto") && strcmp(origem, "manual"))) motivo = "payload_invalido";
  else if (modo == SEGURO) motivo = "modo_seguro";

  if (!motivo && strcmp(acao, "definir_modo") == 0) {
    const char* m = d["modo"] | "";
    if (strcmp(origem, "manual") != 0) motivo = "payload_invalido";
    else if (strcmp(m, "manual") == 0) {
      uint32_t dur = d["duracao_s"] | 300;
      if (dur < 60 || dur > 1800) motivo = "payload_invalido";
      else { modo = MANUAL; manualAte = millis() + dur * 1000UL; logf("modo MANUAL por %u s", (unsigned)dur); }
    } else if (strcmp(m, "auto") == 0) { modo = AUTO; logf("modo AUTO"); }
    else motivo = "payload_invalido";
    if (!motivo) {
      ultimoCmdId = cmdId;
      publicarAck(cmdId, "executado", nullptr);
      guardarAck(cmdId, "executado", "");
      publicarEstado();
      return;
    }
  } else if (!motivo && strcmp(acao, "aplicar") == 0) {
    int idx = idxCena(d["cena"] | "");
    const char* s = d["sombra"] | "";
    int novaSombra = strcmp(s, "fechada") == 0 ? 1 : strcmp(s, "aberta") == 0 ? 0 : -1;
    if (idx < 0 || novaSombra < 0) motivo = "payload_invalido";
    else if ((modo == AUTO && strcmp(origem, "auto")) || (modo == MANUAL && strcmp(origem, "manual")))
      motivo = "modo_incompativel";
    else if (novaSombra != sombra && sombra >= 0 &&
             (servoMovendo || millis() - ultimoMovimento < INTERTRAVAMENTO_MS))
      motivo = "intertravamento";
    if (!motivo) {
      cenaIdx = idx;
      aplicarLeds(idx);
      ultimoCmdId = cmdId;
      int alvo = novaSombra ? cfgSombraFechada : SOMBRA_ABERTA_GRAUS;
      bool mover = novaSombra != sombra || servoAtual != alvo;
      sombra = novaSombra;
      logf("cena %s · sombra %s (%s)", CENAS[idx], novaSombra ? "fechada" : "aberta", origem);
      if (mover) { cmdEmExecucao = cmdId; iniciarMovimento(alvo); }   // ack "executado" ao terminar
      else { publicarAck(cmdId, "executado", nullptr); guardarAck(cmdId, "executado", ""); publicarEstado(); }
      return;
    }
  } else if (!motivo) {
    motivo = "payload_invalido";
  }
  publicarAck(cmdId, "rejeitado", motivo);
  guardarAck(cmdId, "rejeitado", motivo);
}

void processarConfig(byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len) || d["v"] != 1) { logf("config inválida ignorada"); return; }
  if (d["seguro_apos_s"].is<uint32_t>()) {
    uint32_t v = d["seguro_apos_s"];
    if (v >= 10 && v <= 600 && v != cfgSeguroAposS) { cfgSeguroAposS = v; salvarU("seguro_s", v); }
  }
  if (d["sombra_fechada_graus"].is<int>()) {
    int v = d["sombra_fechada_graus"];
    if (v >= 45 && v <= 120 && v != cfgSombraFechada) { cfgSombraFechada = v; salvarI("fechada", v); }
  }
  logf("config remota aplicada e salva na NVS: seguro_apos_s=%u sombra_fechada=%d", (unsigned)cfgSeguroAposS,
       cfgSombraFechada);
}

void aoReceber(char* topic, byte* payload, unsigned int len) {
  if (strcmp(topic, T_COMANDO) == 0) { processarComando(payload, len); return; }
  if (strcmp(topic, T_CONFIG) == 0) { processarConfig(payload, len); return; }
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;
  bool online = d["online"] | false;
  if (strcmp(topic, T_BACKEND) == 0) {
    backendOnline = online;
    logf("backend %s", online ? "online" : "OFFLINE");
    if (!online) entrarSeguro("backend_offline");
  } else if (strncmp(topic, "luzambiente/v1/sensor/", 22) == 0) {
    sensorOnline = online;
    logf("sensor %s", online ? "online" : "OFFLINE");
    if (!online) entrarSeguro("sensor_offline");
  }
  sairSeguroSePuder();
}

// ---------------------------------------------------------------- rede (não bloqueante)
void cuidarWifi() {
  uint32_t agora = millis();
  if (wifiPausadoAte && (int32_t)(agora - wifiPausadoAte) < 0) return;
  if (wifiPausadoAte) { wifiPausadoAte = 0; logf("fim do teste: religando o Wi-Fi"); }
  if (WiFi.status() == WL_CONNECTED) return;
  if (agora - ultimaTentativaWifi < 10000 && ultimaTentativaWifi) return;
  ultimaTentativaWifi = agora;
  logf("Wi-Fi: conectando em %s", cfgSsid.c_str());
  WiFi.disconnect();
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());
}

void cuidarMqtt() {
  uint32_t agora = millis();
  if (mqtt.connected()) { mqttCaiuEm = 0; return; }
  if (!mqttCaiuEm) { mqttCaiuEm = agora ? agora : 1; backendOnline = sensorOnline = false; logf("MQTT desconectado"); }
  if (modo != SEGURO && agora - mqttCaiuEm > cfgSeguroAposS * 1000UL) entrarSeguro("mqtt_desconectado");
  if (WiFi.status() != WL_CONNECTED) return;
  if (agora - ultimaTentativaMqtt < 3000 && ultimaTentativaMqtt) return;
  ultimaTentativaMqtt = agora;
  char offline[64];
  snprintf(offline, sizeof(offline), "{\"v\":1,\"device\":\"%s\",\"online\":false}", DEVICE);
  mqtt.setServer(cfgHost.c_str(), MQTT_PORT);
  if (!mqtt.connect(DEVICE, MQTT_USER, MQTT_PASS, T_STATUS, 1, true, offline)) {
    logf("MQTT: falhou (estado %d) em %s:%d, nova tentativa em 3 s", mqtt.state(), cfgHost.c_str(), MQTT_PORT);
    return;
  }
  JsonDocument d;
  d["v"] = 1; d["device"] = DEVICE; d["online"] = true; d["fw"] = FW_VERSION;
  d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI();
  char buf[160]; size_t n = serializeJson(d, buf);
  mqtt.publish(T_STATUS, (const uint8_t*)buf, n, true);
  // Refaz as assinaturas a cada reconexão
  mqtt.subscribe(T_COMANDO, 1);
  mqtt.subscribe(T_CONFIG, 1);
  mqtt.subscribe(T_BACKEND, 1);
  mqtt.subscribe(T_SENSOR, 1);
  logf("MQTT conectado em %s (assinaturas refeitas)", cfgHost.c_str());
  publicarEstado();
}

// ---------------------------------------------------------------- Serial (configuração e testes)
void cuidarSerial() {
  if (!Serial.available()) return;
  String l = Serial.readStringUntil('\n'); l.trim();
  if (l == "show") {
    logf("fw %s modo=%s cena=%s sombra=%d wifi=%s ip=%s host=%s mqtt=%s backend=%d sensor=%d", FW_VERSION, nomeModo(),
         cenaIdx >= 0 ? CENAS[cenaIdx] : "-", sombra, cfgSsid.c_str(), WiFi.localIP().toString().c_str(),
         cfgHost.c_str(), mqtt.connected() ? "ok" : "off", backendOnline, sensorOnline);
  } else if (l.startsWith("wifi ")) {
    int sp = l.indexOf(' ', 5);
    if (sp < 0) { logf("uso: wifi <ssid> <senha>"); return; }
    cfgSsid = l.substring(5, sp); cfgPass = l.substring(sp + 1);
    salvar("ssid", cfgSsid); salvar("pass", cfgPass);
    logf("Wi-Fi salvo na NVS: %s (reconectando)", cfgSsid.c_str());
    ultimaTentativaWifi = 0; WiFi.disconnect();
  } else if (l.startsWith("host ")) {
    cfgHost = l.substring(5); salvar("host", cfgHost);
    logf("broker salvo na NVS: %s", cfgHost.c_str()); mqtt.disconnect();
  } else if (l.startsWith("wifioff")) {
    int s = l.length() > 8 ? l.substring(8).toInt() : 40;
    wifiPausadoAte = millis() + s * 1000UL;
    WiFi.disconnect();
    logf("TESTE DE FALHA: Wi-Fi desligado por %d s", s);
  } else if (l == "reset") {
    prefs.begin("cfg", false); prefs.clear(); prefs.end(); logf("NVS apagada, reiniciando"); ESP.restart();
  } else if (l == "reboot") {
    ESP.restart();
  } else if (l.length()) {
    logf("comandos: show · wifi <ssid> <senha> · host <ip> · wifioff [s] · reset · reboot");
  }
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  delay(200);
  logf("Luz Ambiente · atuador01 · fw %s · contrato v1.1", FW_VERSION);
  for (int i = 0; i < 4; i++) { pinMode(PIN_LED[i], OUTPUT); digitalWrite(PIN_LED[i], LOW); }  // estado seguro
  pinMode(PIN_SERVO, OUTPUT); digitalWrite(PIN_SERVO, LOW);
  servoOk = ledcAttach(PIN_SERVO, 50, 16);
  if (servoOk) soltarServo(); else logf("ERRO: LEDC do servo falhou");
  carregarConfig();
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(15);
  mqtt.setCallback(aoReceber);
  ArduinoOTA.setHostname(DEVICE);
  ArduinoOTA.setPassword(OTA_PASS);
  ArduinoOTA.onStart([]() { soltarServo(); aplicarLeds(-1); logf("OTA: recebendo firmware novo"); });
  ArduinoOTA.onEnd([]() { logf("OTA: concluído, reiniciando"); });
  mqttCaiuEm = 1;
}

void loop() {
  static bool otaIniciado = false;
  if (WiFi.status() == WL_CONNECTED && !otaIniciado) { ArduinoOTA.begin(); otaIniciado = true;
    logf("Wi-Fi OK: ip %s rssi %d", WiFi.localIP().toString().c_str(), WiFi.RSSI()); }
  ArduinoOTA.handle();
  cuidarSerial();
  cuidarWifi();
  cuidarMqtt();
  mqtt.loop();
  cuidarServo();
  uint32_t agora = millis();
  if (modo == MANUAL && (int32_t)(agora - manualAte) >= 0) {
    modo = AUTO; logf("timeout do MANUAL: voltando para AUTO"); publicarEstado();
  }
  if (modo == SEGURO) digitalWrite(PIN_LED[0], (agora / 500) % 2);   // LED 1 pisca a 1 Hz
  if (agora - ultimoEstado > 30000) publicarEstado();                  // heartbeat a cada 30 s
}
