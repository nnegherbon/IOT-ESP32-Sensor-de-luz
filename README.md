# 🌿 Luz Ambiente: proteção solar automática para plantas sensíveis

Projeto de **Internet das Coisas** com dois **ESP32** comunicando por **MQTT**. Um nó mede a luz que chega à planta;
o outro sinaliza a situação com LEDs e **fecha uma sombra com um servo** quando o sol fica extremo. Uma dashboard
web grava todo o histórico e mostra tudo em tempo real.

```
luz → LDR → ESP32 sensor ──Wi-Fi/MQTT──▶ Mosquitto (Docker, no PC) ──MQTT──▶ ESP32 atuador → 4 LEDs + servo (sombra)
                                              │
                                              ▼  assina iot/luzambiente/#
                               FastAPI + PostgreSQL ──REST/WebSocket──▶ dashboard React
```

## Problema e usuário

Plantas sensíveis (samambaias, orquídeas, mudas, suculentas recém-transplantadas) **queimam as folhas e desidratam**
quando pegam sol direto e intenso. O **usuário** é quem cultiva essas plantas em casa, na varanda, em horta urbana
ou estufa pequena e não está ao lado delas o dia todo para puxar uma sombra na hora certa.

**Proposta de valor:** *a planta se protege sozinha do sol forte e você acompanha pelo celular ou pelo PC*.

## Estado atual (novembro/2026)

Montado e validado em bancada, de ponta a ponta:

| Parte | Como funciona |
|---|---|
| **Nó sensor** (`firmware/n1/Sensor_de_luz`) | lê o LDR no GPIO34 e classifica em 4 cenas: escuro < 150 · ambiente 150–399 · alta 400–999 · extrema ≥ 1000. Publica a **cena** quando ela muda e a **telemetria** (leitura bruta) a cada 2 s, com presença/LWT |
| **Nó atuador** (`firmware/n1/Atuador_LED`) | acende o LED da cena (escuro → LED 1 · ambiente → LED 2 · alta → LED 3 · extrema → os 4), publica a confirmação retida e a presença/LWT, e move a **sombra**: aberta 15°, fechada 120°, **só na cena extrema** |
| **Broker** | Mosquitto 2 local, no `docker compose` da dashboard (porta 1883, sem senha) |
| **Dashboard** (`dashboard-prototipo/`) | FastAPI + PostgreSQL + React: leituras, mín/máx/média, gráfico, transições de cena, confirmações e latência, presença das placas, posição da sombra, alertas, histórico e exportação CSV/JSON. O banco fica num volume Docker e sobrevive a reinícios |
| **Alimentação** | as duas placas só pelo USB, **sem fonte externa**; o servo usa o VIN (5 V do USB) |

Limitações conhecidas:

- Os limites 150/400/1000 ainda **não foram calibrados**: com a luz comum de um quarto o LDR lê ~1.500–1.800, que já é
  *extrema*.
- O **servo SG90 queimou** em 22/11/2026 (ver as precauções abaixo). O firmware e a dashboard estão prontos; falta
  instalar e calibrar o servo novo (MG90S recomendado).
- O broker não tem usuário/senha, e os ESP32 usam o **IP fixo do PC** (`MQTT_HOST` no `.ino`).
- O contrato MQTT em uso é o da N1 (`iot/luzambiente/...`). O [contrato v1](contrato/v1/CONTRATO_v1.md), com
  versionamento, ack por `cmd_id` e modos AUTO/MANUAL/SEGURO, é o alvo da N3.

## Como rodar

**1. Broker + dashboard** (pré-requisito: Docker com Compose):

```bash
cd dashboard-prototipo
cp .env.example .env          # defina ao menos POSTGRES_PASSWORD
docker compose up -d --build  # sobe mosquitto, db, backend e frontend
```

Painel em <http://localhost:8080> (porta `HTTP_PORT` do `.env`). Detalhes em
[`dashboard-prototipo/README.md`](dashboard-prototipo/README.md).

**2. Firmwares** (Arduino IDE 2 com o core **esp32 da Espressif**, placa *ESP32 Dev Module*, e as bibliotecas
**PubSubClient** e **ArduinoJson**). Em cada `.ino` de `firmware/n1/`, preencha:

- `WIFI_SSID` / `WIFI_PASSWORD`: a rede Wi-Fi (**nunca faça commit desses valores**);
- `MQTT_HOST`: o IP do PC que roda o Docker na rede Wi-Fi. Nunca use `localhost`: para o ESP32, esse é ele mesmo.

Com as duas placas no USB, **confirme pelo Monitor Serial (115200) qual porta COM é qual** antes de gravar: o sensor
imprime `Luz: N`, e o atuador fica quieto até receber uma cena.

## Hardware

![Esquema do nó sensor](docs/hardware/esquema_eletrico/esquema_sensor.png)

![Esquema do nó atuador](docs/hardware/esquema_eletrico/esquema_atuador.png)

Pinagem completa e pinos evitados: [mapa de pinos](docs/hardware/mapa_de_pinos.md).

## ⚠️ Precauções de hardware

- O ESP32 trabalha com **3,3 V**: nenhum sinal de 5 V vai direto a um GPIO.
- **LDR só em pinos do ADC1** (GPIO 32–39); o ADC2 não lê com o Wi-Fi ligado. O LDR precisa de um resistor de 10 kΩ
  formando divisor e precisa **enxergar a luz**: dentro de uma caixa fechada ele lê escuro.
- **Todo LED com resistor em série** (330 Ω); nenhuma carga alimentada por GPIO.
- **Servo pelo VIN, sem fonte externa**, por isso: carga leve, ângulos com folga dos batentes e **PWM desligado depois
  de cada movimento**. O SG90 queimou ao ficar ~3 min travado segurando a ponta (0°), com o braço sem parafuso. Se o
  servo zumbir sem girar ou esquentar, desligue.
- Placas com conversor USB **CP2102** precisam do driver da Silicon Labs no Windows para a porta COM aparecer. Use um
  cabo USB **de dados** (cabos só de carga não aparecem como porta).

## Documentação e diagramas

| Item | Conteúdo |
|---|---|
| [mapa de pinos](docs/hardware/mapa_de_pinos.md) | pinagem dos dois nós, alimentação do servo, pinos evitados |
| [esquemas elétricos](docs/hardware/esquema_eletrico/) | `esquema.py` (schemdraw) gera os `.svg`/`.png` |
| [arquitetura-alvo](docs/diagramas/arquitetura.svg) | visão N3 (contrato v1, TLS, login) |
| [fluxo do comando](docs/diagramas/fluxo_comando.png) · [fluxograma do atuador](docs/diagramas/fluxograma_atuador.png) | desenho N3 com AUTO/MANUAL/SEGURO |
| [contrato v1](contrato/v1/CONTRATO_v1.md) | contrato MQTT congelado: schemas e exemplos (`validar.py`) |
| [dashboard](dashboard-prototipo/README.md) | instalação, banco, API, alertas, testes |

## Estrutura do repositório

```text
├── firmware/n1/                  firmwares em uso (Sensor_de_luz, Atuador_LED) — Arduino IDE
├── dashboard-prototipo/          broker Mosquitto + backend FastAPI + PostgreSQL + frontend React (docker compose)
├── docs/
│   ├── hardware/                 mapa de pinos e esquemas elétricos
│   └── diagramas/                arquitetura, fluxos e fluxograma (.mmd fonte + .svg/.png)
├── contrato/v1/                  contrato MQTT v1 (alvo da N3)
└── (legado) backend/, firmware/esp32_*, docs/*.md, IOT-ESP32-Sensor-de-luz
                                  versão anterior, de outro escopo (som/presença, 1 LED no GPIO13).
                                  Não usar a pinagem nem as instruções dela.
```

## Como reproduzir os artefatos

```bash
pip install jsonschema schemdraw matplotlib
npm install -g @mermaid-js/mermaid-cli

python contrato/v1/validar.py                         # valida os exemplos do contrato v1
python docs/hardware/esquema_eletrico/esquema.py      # redesenha os esquemas elétricos
for f in docs/diagramas/*.mmd; do mmdc -i "$f" -o "${f%.mmd}.png" -b white -s 2; mmdc -i "$f" -o "${f%.mmd}.svg" -b white; done
```

## 👥 Equipe

| Integrante | Responsabilidade |
|---|---|
| Ruan Pablo de Lima Pereira | nó sensor: divisor/ADC, fluxograma do sensor e fluxo do dado, parâmetros de decisão |
| Rodrigo Bonifácio Conceição | nó atuador: máquina de estados, intertravamento, servo |
| Vinicius Clemente Negherbon | contrato MQTT v1, repositório |
| Bianca Barp | esquema elétrico, BOM, mapa de pinos, revisão do documento |
| Guilherme Pietro | arquitetura-alvo, fluxo do comando, protótipo do dashboard, plano de falhas, cronograma e riscos |

## 📄 Licença

Projeto acadêmico, sem licença de software definida.
