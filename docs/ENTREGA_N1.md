# Guia de entrega — situação atual e caminho adiante

## O que mudou desde a proposta da Aula 02

A proposta original ("Luz Ambiente Inteligente: Som & Presença") previa
microfone MAX9814, PIR HC-SR501 e fita RGB WS2812B. O hardware que o grupo
tem em mãos hoje é outro: **2 ESP32, um LDR e um LED comum** — praticamente
os mesmos componentes do projeto-base do professor.

Isso não é um desvio silencioso: está documentado em
[RISCOS.md](RISCOS.md#pendência-de-escopo-não-é-bug-é-hardware-faltando) como
pendência de escopo, com destaque para o fato de que, sem PIR (ou substituto),
a metade "ocupação" da família temática ainda não é demonstrável.

## Como o código absorve isso sem retrabalho

Toda a lógica das três dimensões (luz, som, ocupação) já existe em
`backend/app/automation.py`, testada. O que muda com o hardware disponível é
só quais flags estão ligadas:

| Flag | Hoje | Quando o sensor chegar |
|---|---|---|
| `SOM_HABILITADO` | `false` — som fixo em 0 | `true`, depois de montar o MAX9814 e calibrar |
| `OCUPACAO_HABILITADA` | `false` — sempre "ocupado" | `true`, depois de montar o PIR (ou um botão) |

O firmware segue o mesmo princípio: os trechos de leitura de som, presença e
RGB estão no arquivo, dentro de blocos `#if 0 ... #endif` marcados "SOM:",
"PRESENCA:" e "RGB:". Trocar para `#if 1` é o suficiente.

## Mapa: requisito da proposta → onde está hoje

| Item pedido na proposta | Situação | Onde está |
|---|---|---|
| Medir/classificar som | código pronto, sensor pendente | `classificar_som()` em `automation.py`; `#if 0 // SOM:` no firmware |
| Detectar presença (PIR) | código pronto, sensor pendente | `ambiente_ocupado()` em `automation.py`; `#if 0 // PRESENCA:` no firmware |
| Controlar iluminação por presença e som | parcialmente ativo | luz ativa hoje; som e ocupação entram assim que as flags ligarem |
| Desligar quando não há ocupação | logicamente pronto, não demonstrável ainda | primeira condição de `decidir()` — mas `ocupado` é sempre `True` sem PIR |
| Apagar/atenuar com luz suficiente | **ativo hoje** | `classificar_luz()` em `automation.py` |
| Integração demonstrada em laboratório | ativa hoje, com LED comum | `docs/MONTAGEM.md` |
| Primeiro risco técnico | atualizado para o hardware real | `docs/RISCOS.md` |

## O que dá para demonstrar hoje

Com o hardware atual, o ciclo completo funciona de ponta a ponta: cobrir o
LDR publica uma leitura mais baixa, o backend decide "suave", publica o
comando, o LED acende, o atuador confirma, o dashboard atualiza. É o mesmo
ciclo sensor → MQTT → backend → MQTT → atuador → MQTT → dashboard que a
proposta descreve — só que hoje dirigido pela luz, não pelo som ou pela
presença.

## Antes da apresentação

- [ ] Confirmar com o professor se falta PIR/microfone é aceitável nesta
      entrega, ou se um botão substituto é necessário
- [ ] Divisor de tensão do LDR confirmado (resistor certo — ver MONTAGEM.md)
- [ ] Rede testada no local **com antecedência** (risco R3)
- [ ] `firmware/esp32_standalone` gravado como plano B
- [ ] Valores de calibração da luz preenchidos e commitados
- [ ] `docker compose run --rm backend pytest` passando
- [ ] Roteiro de demonstração: cobrir o LDR, descobrir, mostrar o dashboard
