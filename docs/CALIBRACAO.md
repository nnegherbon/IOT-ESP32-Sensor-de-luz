# Calibração

## Luz (LDR) — sensor ativo hoje

Os números padrão (`AUTOMATION_LUZ_LIMIAR=40`, `AUTOMATION_LUZ_HISTERESE=8`)
são chutes. Eles precisam ser medidos no ambiente onde o protótipo vai rodar.

### Procedimento

1. Grave `firmware/esp32_sensor` (ou o standalone) e abra o monitor serial —
   ele já imprime `luz: NN.N%` a cada leitura.
2. **Ambiente escuro** (luz apagada, ou tape o LDR): anote o valor típico.
3. **Ambiente claro** (luz acesa, ou o mesmo ponto onde vão demonstrar): anote
   o valor típico.
4. O limiar (`AUTOMATION_LUZ_LIMIAR`) fica entre os dois — normalmente mais
   perto do valor escuro, para não acender o LED com qualquer luz ambiente
   residual.
5. A histerese (`AUTOMATION_LUZ_HISTERESE`) evita o LED piscando quando a
   leitura fica rondando o limiar. Comece com ~20% da distância entre os dois
   valores medidos e ajuste ouvindo/vendo o comportamento.
6. Ajuste no `.env` e reinicie o backend: `docker compose up -d --build backend`.
   **Não precisa regravar o ESP32 para isso** — é uma vantagem direta de a
   regra estar no backend, não no firmware.

### Registro do grupo

| Item | Valor medido | Quem mediu | Data |
|---|---|---|---|
| Luz no escuro (%) | | | |
| Luz no claro (%) | | | |
| AUTOMATION_LUZ_LIMIAR | | | |
| AUTOMATION_LUZ_HISTERESE | | | |

---

## Som (microfone) — quando o MAX9814 chegar

Esta seção fica pronta para quando o sensor for montado. O código de leitura
já existe, comentado, em `firmware/esp32_sensor/src/main.cpp` (blocos
`#if 0 // SOM:`).

### Por que pico a pico, não uma leitura isolada

O MAX9814 entrega a forma de onda do áudio, centrada em ~1,25 V (≈1550 no ADC
de 12 bits). Uma leitura isolada cai num ponto aleatório da senoide — não
tem relação com o volume. O que carrega informação é a **amplitude**: por
isso o firmware comentado amostra uma janela de 50 ms, guarda o mínimo e o
máximo, e usa a diferença (pico a pico).

### Procedimento (depois de descomentar o bloco SOM no firmware)

1. **Piso.** Com a sala em silêncio, anote o maior `pp` que aparecer em uns
   20 s no monitor serial. Some ~20% de folga. Isso é `PP_SILENCIO`.
2. **Teto.** Bata palma perto do microfone. Anote o `pp` típico dos picos —
   não o recorde absoluto. Isso é `PP_MAXIMO`.
3. Coloque os dois valores nas constantes do firmware.
4. Ajuste `AUTOMATION_SOM_MEDIO` e `AUTOMATION_SOM_ALTO` no `.env` até a
   troca de cena acontecer onde o grupo quer, sem precisar regravar o ESP32.
5. Mude `SOM_HABILITADO=true` no `.env` para o backend passar a usar o valor
   real em vez do fixo.

### Registro do grupo (preencher quando o microfone chegar)

| Item | Valor medido | Quem mediu | Data |
|---|---|---|---|
| PP_SILENCIO | | | |
| PP_MAXIMO | | | |
| AUTOMATION_SOM_MEDIO | | | |
| AUTOMATION_SOM_ALTO | | | |

Voltar ao [índice de montagem](MONTAGEM.md).
