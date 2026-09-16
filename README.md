# Luz Ambiente Inteligente

Disciplina de Internet das Coisas — 6º semestre, Turma B
Família temática 3: Iluminação e ocupação

Iluminação que reage à luminosidade do ambiente: acende quando escurece,
apaga quando há luz suficiente. Som e ocupação fazem parte do desenho e do
código, mas dependem de sensores que ainda não chegaram — ver a seção
"Situação do hardware" abaixo.

```
luminosidade → LDR → ESP32 sensor → Wi-Fi/MQTT → Mosquitto
                                                     ↓
dashboard ← API/WebSocket ← FastAPI + PostgreSQL ← regra de automação
                                                     ↓ MQTT
                                       ESP32 atuador → LED → status
```

O sensor **não** controla o LED diretamente. A decisão acontece no backend e
os dispositivos se conhecem apenas pelo contrato de mensagens MQTT.

## Situação do hardware (setembro/2026)

A proposta original previa microfone, PIR e fita RGB. O que está montado hoje
é **2 ESP32, um LDR e um LED comum**. O projeto todo — backend, firmware e
documentação — está desenhado para que os componentes que faltam entrem sem
retrabalho: o código de som e de presença já existe, comentado, e liga com
uma variável de ambiente. Detalhes em
[docs/ENTREGA_N1.md](docs/ENTREGA_N1.md).

> **Pendência para o professor:** sem PIR (nem um substituto simples, como um
> botão), a metade "ocupação" da família temática ainda não é demonstrável.
> Ver [docs/RISCOS.md](docs/RISCOS.md).

## Início rápido (sem hardware)

Pré-requisito: Docker com Compose.

```bash
cp .env.example .env
docker compose up --build
```

Abra <http://localhost:8000>. Em outro terminal:

```bash
docker compose --profile tools run --rm simulator
```

No simulador, digite níveis de luz (`80`, `10`, `40`) ou `auto` para variar
sozinho. A lâmpada do dashboard muda de acordo. A API interativa fica em
<http://localhost:8000/docs>.

## Hardware

```bash
cp firmware/esp32_sensor/include/secrets.example.h firmware/esp32_sensor/include/secrets.h
cp firmware/esp32_atuador/include/secrets.example.h firmware/esp32_atuador/include/secrets.h
```

Preencha Wi-Fi e o IP do computador onde o Mosquitto roda. Nunca use
`localhost` no ESP32: para ele, esse endereço é o próprio microcontrolador.

Duas armadilhas para ler antes de montar:

- **LDR só em pinos do ADC1** (GPIO 32–36, 39). O ADC2 é compartilhado com o
  Wi-Fi e devolve lixo quando o rádio está ligado.
- **O LDR sozinho não lê nada** — precisa de um resistor formando um divisor
  de tensão. Ver [docs/MONTAGEM.md](docs/MONTAGEM.md).

## Comportamento (hoje)

| Luz | Cena | LED |
|---|---|---|
| clara | `claro` | apagado |
| escura | `suave` | aceso |

Com histerese: subir de "escuro" para "claro" exige cruzar o limiar mais uma
folga, para o LED não piscar quando a luz fica rondando o limite. Quando som
e ocupação forem ativados, a tabela ganha as faixas `media` e `festa` e a
cena `apagada` (sem ocupação) — a lógica já existe e é testada, só falta o
sensor.

Modos: **automático** (a regra decide) e **manual** (o dashboard comanda).

## Documentação

| Documento | Conteúdo |
|---|---|
| [ENTREGA_N1.md](docs/ENTREGA_N1.md) | o que mudou desde a proposta, mapa requisito → código |
| [MONTAGEM.md](docs/MONTAGEM.md) | pinagem, ordem de testes, o que muda quando os sensores chegarem |
| [CONFIGURACAO.md](docs/CONFIGURACAO.md) | `.env`, `secrets.h`, checklist de rede |
| [CONTRATO_MQTT.md](docs/CONTRATO_MQTT.md) | tópicos, payloads, QoS, retenção |
| [CALIBRACAO.md](docs/CALIBRACAO.md) | como achar os limiares de luz (e, depois, de som) |
| [RISCOS.md](docs/RISCOS.md) | riscos técnicos + pendência de escopo (ocupação) |

## Comandos úteis

```bash
docker compose up --build                    # sobe a solução
docker compose logs -f backend mosquitto     # acompanha mensagens e serviços
docker compose run --rm backend pytest       # testes da regra de automação
docker compose down                          # encerra preservando os dados
docker compose down -v                       # encerra e apaga o banco (destrutivo)
mosquitto_sub -h localhost -t 'iot/luzambiente/#' -v   # espia o barramento
```

## Integrantes

| Integrante | Frente |
|---|---|
| Rodrigo Bonifácio Conceição | circuito e testes de ligação |
| Ruan Pablo de Lima Pereira | repositório e documentação |
| Guilherme Pietro Ruiz Costa | sensor de som e calibração |
| Vinícius Clemente Negherbon | sensor de presença |
| Bianca Barp | componentes e arquitetura |

Projeto-base da disciplina:
[edsonvazlopes/Iot_salaInteligente](https://github.com/edsonvazlopes/Iot_salaInteligente).
