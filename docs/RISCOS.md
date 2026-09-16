# Riscos técnicos

A entrega da Aula 02 pedia o primeiro risco técnico. Esta versão reflete o
hardware real disponível hoje (LDR + LED + 2 ESP32) e separa risco técnico
de pendência de escopo — são coisas diferentes e o professor provavelmente
vai perguntar sobre as duas.

## Pendência de escopo (não é bug, é hardware faltando)

### P1 — "Ocupação" da família temática ainda não é demonstrável

**Este é o ponto mais importante para levar ao professor.**

A família temática do grupo é "Iluminação e ocupação". Sem PIR — nem um
substituto simples, como um botão — não há como o sistema saber se há
alguém no ambiente. O backend contorna isso considerando o ambiente sempre
ocupado (`OCUPACAO_HABILITADA=false`), então **hoje o projeto demonstra só a
metade "iluminação"** do tema, com o comportamento equivalente ao
projeto-base do professor (luz → decide → atuador).

- **O que já está pronto para quando resolver:** toda a lógica de ocupação
  (`ambiente_ocupado()` em `automation.py`) existe, é testada, e liga com uma
  variável de ambiente — não precisa reescrever nada.
- **Ação recomendada:** decidir com o professor se um botão simples (mais
  fácil de conseguir que um PIR) é aceitável como sensor de presença para a
  entrega, ou se vale a pena esperar o PIR chegar.

### P2 — Som também está fora do circuito

O microfone MAX9814 também não chegou. O código de leitura está pronto e
comentado (`SOM_HABILITADO=false`). Diferente da ocupação, o som não fazia
parte do nome oficial da família temática — é mais fácil de justificar como
"próxima etapa" sem reabrir a conversa sobre o escopo da N1.

## Riscos técnicos de verdade

### R1 — Divisor de tensão do LDR mal dimensionado

**Severidade: média. Probabilidade: média.**

Um LDR sozinho no ADC não lê nada útil — precisa de um resistor formando um
divisor de tensão. Se o resistor for muito diferente da resistência do LDR
em luz ambiente, a leitura fica sempre perto de 0 ou sempre perto de 4095,
sem faixa de variação útil.

- **Sintoma:** o valor de luminosidade não muda ao cobrir/destampar o sensor,
  ou muda muito pouco.
- **Mitigação:** confirmar o valor do resistor na bancada (ver
  [MONTAGEM.md](MONTAGEM.md)) antes de calibrar limiares.
- **Status:** a confirmar no teste 1 da montagem.

### R2 — ADC2 do ESP32 é inutilizável com Wi-Fi ligado

**Severidade: alta. Probabilidade: alta se ninguém souber disso.**

O ADC2 é compartilhado com o rádio Wi-Fi. Com o Wi-Fi ativo, `analogRead()`
nesses pinos devolve valores errados ou trava.

- **Sintoma:** o LDR funciona no teste isolado e passa a devolver lixo assim
  que o firmware com MQTT é gravado.
- **Mitigação:** usar apenas ADC1 (GPIO 32, 33, 34, 35, 36, 39). O firmware
  já está em GPIO 34.
- **Status:** mitigado no projeto.

### R3 — Rede do laboratório bloqueando os ESP32

**Severidade: média. Probabilidade: média.**

Wi-Fi institucional costuma ter isolamento de clientes, portal cativo ou
somente 5 GHz — qualquer um dos três impede o ESP32 de alcançar o broker.

- **Mitigação:** testar com hotspot de celular ou roteador próprio antes do
  dia da apresentação. Ter `firmware/esp32_standalone` gravado como plano B.
- **Status:** a testar. **Testem isso antes do dia da entrega, não no dia.**

### R4 — Dois atuadores no mesmo prefixo

**Severidade: baixa. Probabilidade: média.**

Simulador e ESP32 rodando juntos assinam o mesmo comando e publicam no mesmo
status; o dashboard passa a mostrar estado inconsistente.

- **Mitigação:** rodar um atuador por vez, ou usar `MQTT_BASE_TOPIC`
  diferentes.
- **Status:** documentado no [contrato](CONTRATO_MQTT.md).

### R5 — Nível lógico e alimentação (quando a fita RGB chegar)

**Severidade: média. Probabilidade: média — ainda não se aplica hoje.**

O WS2812B espera ~3,5 V no DIN e o ESP32 entrega 3,3 V; e cada LED em branco
total puxa ~60 mA. Isso só importa quando o firmware RGB comentado for
reativado.

- **Mitigação planejada:** resistor de 330 Ω na linha de dados, capacitor de
  1000 µF, `setMaxPowerInVoltsAndMilliamps`, poucos LEDs na primeira
  montagem. Já está no código comentado.
- **Status:** não aplicável com o hardware atual (LED comum).

Voltar ao [README](../README.md).
