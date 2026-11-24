/* LUZ AMBIENTE · NÓ SENSOR (sensor01) · contrato MQTT v1.1
 *
 * Mede a luz (LDR + 10 kΩ no GPIO34, ADC1) e publica a telemetria bruta: o sensor NÃO decide, o backend decide.
 *   luzambiente/v1/sensor/sensor01/telemetria  a cada intervalo_ms (padrão 2 s), QoS 0
 *   luzambiente/v1/sensor/sensor01/status      retido + LWT (online/offline)
 *   luzambiente/v1/sensor/sensor01/config      retido, vindo do backend: intervalo_ms, limite_local (salvos na NVS)
 * Validação da leitura: média de 16 amostras; "saturado" (>= 4090: resistor de 10 kΩ solto ou curto no 3V3)
 *   e "instavel" (desvio padrão alto: pino do LDR solto, flutuando) viram sensor_ok=false + falha.
 * Regra local (funciona sem rede): LED azul da placa (GPIO2) aceso quando a luz passa de limite_local;
 *   pisca rápido quando a leitura é inválida.
 * Hora: NTP quando há internet (hora_sync=true e campo ts); sem NTP, hora_sync=false e o backend carimba.
 * Laço não bloqueante (millis), reconexão automática, OTA (ArduinoOTA), logs no Serial.
 * Credenciais: secrets.h (fora do Git). Modelo: secrets.example.h.
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <time.h>
#include "secrets.h"

#define FW_VERSION "3.0.1"  // 3.0.1: versão usada para demonstrar a atualização por OTA (R17)
static const char* DEVICE = "sensor01";
constexpr uint8_t PIN_LDR = 34;
constexpr uint8_t PIN_LED_LOCAL = 2;     // LED azul da própria placa
constexpr int AMOSTRAS = 16;
constexpr float DESVIO_MAX = 250.0;      // acima disso o pino está flutuando (LDR solto)

#define BASE "luzambiente/v1/sensor/sensor01/"
static const char* T_STATUS = BASE "status";
static const char* T_TELEMETRIA = BASE "telemetria";
static const char* T_CONFIG = BASE "config";

Preferences prefs;
String cfgSsid, cfgPass, cfgHost;
uint32_t cfgIntervalo = 2000;
int cfgLimiteLocal = 1000;

WiFiClient net;
PubSubClient mqtt(net);
uint32_t seq = 0, ultimaTelemetria = 0, ultimaTentativaWifi = 0, ultimaTentativaMqtt = 0, wifiPausadoAte = 0;
int ultimaLeitura = 0;
bool leituraOk = true;
const char* falha = nullptr;
bool ntpIniciado = false;

void logf(const char* fmt, ...) {
  char buf[200];
  va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);
  Serial.printf("[%8lu] %s\n", (unsigned long)millis(), buf);
}

void carregarConfig() {
  prefs.begin("cfg", true);
  cfgSsid = prefs.getString("ssid", WIFI_SSID);
  cfgPass = prefs.getString("pass", WIFI_PASS);
  cfgHost = prefs.getString("host", MQTT_HOST);
  cfgIntervalo = prefs.getUInt("intervalo", 2000);
  cfgLimiteLocal = prefs.getInt("limite", 1000);
  prefs.end();
  logf("config: wifi=%s host=%s intervalo_ms=%u limite_local=%d", cfgSsid.c_str(), cfgHost.c_str(),
       (unsigned)cfgIntervalo, cfgLimiteLocal);
}
void salvar(const char* k, const String& v) { prefs.begin("cfg", false); prefs.putString(k, v); prefs.end(); }

// Média e desvio de 16 leituras seguidas (~1 ms no total)
void medir() {
  long soma = 0; long soma2 = 0;
  for (int i = 0; i < AMOSTRAS; i++) { int v = analogRead(PIN_LDR); soma += v; soma2 += (long)v * v; }
  int media = soma / AMOSTRAS;
  float var = (float)soma2 / AMOSTRAS - (float)media * media;
  float desvio = var > 0 ? sqrtf(var) : 0;
  ultimaLeitura = media;
  if (media >= 4090) { leituraOk = false; falha = "saturado"; }
  else if (desvio > DESVIO_MAX) { leituraOk = false; falha = "instavel"; }
  else { leituraOk = true; falha = nullptr; }
}

void publicarTelemetria() {
  JsonDocument d;
  d["v"] = 1; d["device"] = DEVICE; d["seq"] = seq++; d["uptime_ms"] = millis();
  d["ldr_raw"] = ultimaLeitura; d["amostras"] = AMOSTRAS; d["rssi"] = WiFi.RSSI();
  d["sensor_ok"] = leituraOk;
  if (falha) d["falha"] = falha;
  time_t t = time(nullptr);
  bool sync = t > 1700000000;
  d["hora_sync"] = sync;
  if (sync) { char ts[24]; strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", gmtime(&t)); d["ts"] = ts; }
  char buf[300]; size_t n = serializeJson(d, buf);
  bool ok = mqtt.connected() && mqtt.publish(T_TELEMETRIA, (const uint8_t*)buf, n, false);
  logf("Luz: %d %s%s seq=%u %s", ultimaLeitura, leituraOk ? "ok" : "FALHA ", falha ? falha : "",
       (unsigned)(seq - 1), ok ? "publicado" : "(sem broker: só regra local)");
}

void aoReceber(char* topic, byte* payload, unsigned int len) {
  if (strcmp(topic, T_CONFIG) != 0) return;
  JsonDocument d;
  if (deserializeJson(d, payload, len) || d["v"] != 1) { logf("config inválida ignorada"); return; }
  prefs.begin("cfg", false);
  if (d["intervalo_ms"].is<uint32_t>()) {
    uint32_t v = d["intervalo_ms"];
    if (v >= 1000 && v <= 60000) { cfgIntervalo = v; prefs.putUInt("intervalo", v); }
  }
  if (d["limite_local"].is<int>()) {
    int v = d["limite_local"];
    if (v >= 1 && v <= 4095) { cfgLimiteLocal = v; prefs.putInt("limite", v); }
  }
  prefs.end();
  logf("config remota salva na NVS: intervalo_ms=%u limite_local=%d", (unsigned)cfgIntervalo, cfgLimiteLocal);
}

void cuidarWifi() {
  uint32_t agora = millis();
  if (wifiPausadoAte && (int32_t)(agora - wifiPausadoAte) < 0) return;
  if (wifiPausadoAte) { wifiPausadoAte = 0; logf("fim do teste: religando o Wi-Fi"); }
  if (WiFi.status() == WL_CONNECTED) {
    if (!ntpIniciado) { configTime(0, 0, "pool.ntp.org", "time.google.com"); ntpIniciado = true; }
    return;
  }
  if (agora - ultimaTentativaWifi < 10000 && ultimaTentativaWifi) return;
  ultimaTentativaWifi = agora;
  logf("Wi-Fi: conectando em %s", cfgSsid.c_str());
  WiFi.disconnect();
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());
}

void cuidarMqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  uint32_t agora = millis();
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
  mqtt.subscribe(T_CONFIG, 1);     // refeita a cada reconexão
  logf("MQTT conectado em %s", cfgHost.c_str());
}

void cuidarSerial() {
  if (!Serial.available()) return;
  String l = Serial.readStringUntil('\n'); l.trim();
  if (l == "show") {
    logf("fw %s luz=%d ok=%d wifi=%s ip=%s host=%s mqtt=%s intervalo=%u limite_local=%d", FW_VERSION, ultimaLeitura,
         leituraOk, cfgSsid.c_str(), WiFi.localIP().toString().c_str(), cfgHost.c_str(),
         mqtt.connected() ? "ok" : "off", (unsigned)cfgIntervalo, cfgLimiteLocal);
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
    logf("TESTE DE FALHA: Wi-Fi desligado por %d s (a regra local continua)", s);
  } else if (l == "reset") {
    prefs.begin("cfg", false); prefs.clear(); prefs.end(); logf("NVS apagada, reiniciando"); ESP.restart();
  } else if (l == "reboot") {
    ESP.restart();
  } else if (l.length()) {
    logf("comandos: show · wifi <ssid> <senha> · host <ip> · wifioff [s] · reset · reboot");
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  logf("Luz Ambiente · sensor01 · fw %s · contrato v1.1", FW_VERSION);
  pinMode(PIN_LED_LOCAL, OUTPUT);
  digitalWrite(PIN_LED_LOCAL, LOW);
  analogReadResolution(12);
  pinMode(PIN_LDR, INPUT);
  carregarConfig();
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(15);
  mqtt.setCallback(aoReceber);
  ArduinoOTA.setHostname(DEVICE);
  ArduinoOTA.setPassword(OTA_PASS);
  ArduinoOTA.onStart([]() { logf("OTA: recebendo firmware novo"); });
  ArduinoOTA.onEnd([]() { logf("OTA: concluído, reiniciando"); });
}

void loop() {
  static bool otaIniciado = false;
  if (WiFi.status() == WL_CONNECTED && !otaIniciado) {
    ArduinoOTA.begin(); otaIniciado = true;
    logf("Wi-Fi OK: ip %s rssi %d", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  ArduinoOTA.handle();
  cuidarSerial();
  cuidarWifi();
  cuidarMqtt();
  mqtt.loop();
  uint32_t agora = millis();
  if (agora - ultimaTelemetria >= cfgIntervalo) {
    ultimaTelemetria = agora;
    medir();
    publicarTelemetria();
  }
  // Regra local, sem depender da rede: LED azul = luz forte; piscando rápido = leitura inválida
  if (!leituraOk) digitalWrite(PIN_LED_LOCAL, (agora / 150) % 2);
  else digitalWrite(PIN_LED_LOCAL, ultimaLeitura >= cfgLimiteLocal ? HIGH : LOW);
}
