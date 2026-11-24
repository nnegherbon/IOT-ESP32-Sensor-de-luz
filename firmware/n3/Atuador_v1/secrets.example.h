// Copie para secrets.h (que fica fora do Git) e preencha. Wi-Fi e broker também podem ser trocados
// depois pelo Serial (wifi <ssid> <senha> · host <ip>), e ficam salvos na NVS.
#pragma once
#define WIFI_SSID "SUA_REDE"
#define WIFI_PASS "SUA_SENHA"
#define MQTT_HOST "192.168.0.10"     // IP do PC que roda o docker compose
#define MQTT_PORT 1883
#define MQTT_USER "atuador01"
#define MQTT_PASS "MQTT_PASS_ATUADOR01 do .env"
#define OTA_PASS "SENHA_OTA"
