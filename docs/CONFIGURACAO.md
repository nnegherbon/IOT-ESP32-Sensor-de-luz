# Configuração

Há dois lugares onde se configura endereço de rede, e confundi-los é o erro
mais comum do projeto.

## `.env` — configura o Docker

```bash
cp .env.example .env
```

`MQTT_HOST=mosquitto` é o **nome do serviço no Docker Compose**. O backend, que
roda dentro da mesma rede Docker, encontra o broker por esse nome. Não troque
por IP a menos que esteja rodando o backend fora do Docker.

| Variável | Padrão | O que faz |
|---|---|---|
| `MQTT_BASE_TOPIC` | `iot/luzambiente` | prefixo dos tópicos do grupo |
| `AUTOMATION_LUZ_LIMIAR` | 40 | % de luminosidade abaixo da qual está "escuro" |
| `AUTOMATION_LUZ_HISTERESE` | 8 | quanto a luz precisa subir para voltar a "claro" |
| `SOM_HABILITADO` | `false` | `false` enquanto o MAX9814 não é montado — ver abaixo |
| `SOM_VALOR_PADRAO` | 0 | nível de som usado quando o som está desabilitado |
| `AUTOMATION_SOM_MEDIO` | 25 | % de som que sobe para a cena média |
| `AUTOMATION_SOM_ALTO` | 55 | % de som que sobe para a cena festa |
| `AUTOMATION_SOM_HISTERESE` | 6 | quanto precisa cair para descer de faixa de som |
| `OCUPACAO_HABILITADA` | `false` | `false` enquanto o PIR não é montado — ver abaixo |
| `AUTOMATION_BRILHO_MAX` | 120 | teto de brilho (0-255), protege a fonte |
| `AUTOMATION_CARENCIA_S` | 120 | segundos que o ambiente segue ocupado sem movimento (quando o PIR existir) |

Mudou o `.env`? `docker compose up -d --build backend`.

## Sensores desativados por enquanto

O hardware disponível hoje é só LDR + LED (ver
[ENTREGA_N1.md](ENTREGA_N1.md)). Microfone e PIR ainda não foram montados. O
código de leitura de ambos continua no repositório — `automation.py` (regra,
sempre ativa e testada), e os firmwares (leitura de hardware, dentro de
blocos `#if 0 ... #endif` marcados "SOM:" e "PRESENCA:") — só não está em uso.

- Com `SOM_HABILITADO=false`, o backend usa `SOM_VALOR_PADRAO` (0, faixa
  baixa) em vez de esperar uma leitura real.
- Com `OCUPACAO_HABILITADA=false`, o backend considera o ambiente **sempre
  ocupado**, e a decisão depende só da luz.

O dashboard continua mostrando os campos de som e presença; se o simulador
publicar valores, eles aparecem na tela (com um selo "pendente"), mas não
mudam a cena enquanto as flags estiverem `false`.

Para reativar cada um quando o componente chegar:

1. No firmware correspondente, trocar os blocos `#if 0 // SOM:` ou
   `#if 0 // PRESENCA:` por `#if 1`.
2. Ligar o hardware conforme `docs/MONTAGEM.md`.
3. Calibrar (som: `docs/CALIBRACAO.md`).
4. No `.env`, `SOM_HABILITADO=true` ou `OCUPACAO_HABILITADA=true`, e
   `docker compose up -d --build backend`.

## `secrets.h` — configura os ESP32

```bash
cp firmware/esp32_sensor/include/secrets.example.h firmware/esp32_sensor/include/secrets.h
cp firmware/esp32_atuador/include/secrets.example.h firmware/esp32_atuador/include/secrets.h
```

Aqui `MQTT_HOST` é o **IP do computador** que roda o Docker, na rede Wi-Fi.
Descubra com `ip addr` (Linux), `ipconfig` (Windows) ou `ifconfig` (macOS) —
algo como `192.168.0.42`.

> **Nunca use `localhost` no ESP32.** Para o ESP32, `localhost` é o próprio
> microcontrolador, e a conexão simplesmente nunca acontece.

`secrets.h` está no `.gitignore`. Senha de Wi-Fi não vai para o GitHub.

## Checklist de rede

- [ ] ESP32 e computador na **mesma** rede Wi-Fi
- [ ] Rede de 2,4 GHz — o ESP32 não enxerga 5 GHz
- [ ] Firewall do computador liberando a porta 1883
- [ ] Rede sem isolamento de clientes (comum em Wi-Fi de faculdade; se for o
      caso, use um roteador próprio ou o hotspot de um celular)

Voltar ao [README](../README.md).
