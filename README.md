# 💡 IOT-ESP32-Sala-Inteligente — Níveis de Luz

Repositório referente ao projeto de **Internet das Coisas (IoT)** desenvolvido com **ESP32**, utilizando um **sensor de luz LDR** para identificar variações de luminosidade no ambiente e acionar um **painel composto por 4 LEDs** como resposta.

O projeto utiliza comunicação **Wi-Fi + MQTT**, com o **HiveMQ** atuando como broker, mantendo o módulo responsável pela leitura do sensor fisicamente separado do módulo responsável pelo acionamento dos LEDs.

---

## 📋 Sobre o projeto

O objetivo é desenvolver um sistema IoT desacoplado, no qual a informação capturada fisicamente pelo sensor percorre uma comunicação em rede antes de gerar uma ação física.

O funcionamento ocorre da seguinte maneira:

1. O **ESP32 Sensor** realiza a leitura da luminosidade através de um sensor **LDR**;
2. A leitura é processada e classificada em uma das **4 cenas de iluminação**;
3. O ESP32 conecta-se à rede Wi-Fi e publica a informação no **broker MQTT HiveMQ**;
4. O **ESP32 Atuador** recebe a mensagem através do MQTT;
5. O Atuador identifica a cena recebida e aciona o nível correspondente no **painel de 4 LEDs**;
6. Após executar o comando, o Atuador publica uma **mensagem de confirmação de status**, fechando o ciclo de comunicação.

### 🔄 Fluxo do sistema

```text
┌─────────────────┐
│   Sensor LDR    │
│                 │
│   ESP32 Sensor  │
└────────┬────────┘
         │
         │ Wi-Fi / MQTT
         ▼
┌─────────────────┐
│     HiveMQ      │
│   MQTT Broker   │
└────────┬────────┘
         │
         │ Wi-Fi / MQTT
         ▼
┌─────────────────┐
│  ESP32 Atuador  │
│                 │
│  Controle LEDs  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Painel 4 LEDs  │
│                 │
│ Nível 1 → LED 1 │
│ Nível 2 → LED 2 │
│ Nível 3 → LED 3 │
│ Nível 4 → LED 4 │
└─────────────────┘
```

---

## 🏗️ Arquitetura do sistema

Para garantir que o projeto não seja apenas uma automação local, o sistema possui dois módulos ESP32 fisicamente separados.

### 📡 Módulo Sensor

Responsável por:

* Realizar a leitura do sensor LDR;
* Processar os valores de luminosidade;
* Classificar a luminosidade em diferentes níveis;
* Estabelecer conexão com a rede Wi-Fi;
* Publicar os dados através do protocolo MQTT;
* Enviar as informações utilizando **JSON**.

### 💡 Módulo Atuador

Responsável por:

* Conectar-se ao broker MQTT;
* Escutar os tópicos de comando;
* Interpretar as mensagens recebidas;
* Desligar o nível de LED anteriormente acionado;
* Acionar o LED correspondente à cena recebida;
* Publicar uma confirmação do estado executado.

### 🔗 Comunicação

A comunicação entre os módulos ocorre exclusivamente através de:

**ESP32 Sensor → Wi-Fi → MQTT HiveMQ → Wi-Fi → ESP32 Atuador**

As mensagens são estruturadas utilizando **JSON**, permitindo uma comunicação organizada e facilmente expansível.

---


## ⚠️ Precauções de hardware

O **ESP32 trabalha com lógica de 3,3 V** e possui maior sensibilidade elétrica quando comparado a placas como o Arduino Uno.

Por isso, alguns cuidados são fundamentais durante a montagem:

* Utilize **um resistor individual para cada LED**;
* Nunca conecte um LED diretamente a um GPIO sem resistor;
* Evite aplicar tensões superiores às especificações dos GPIOs;
* Confira a polaridade dos LEDs antes de energizar o circuito;
* Verifique as conexões na protoboard antes de realizar o upload;
* Desconecte a alimentação durante alterações na montagem.


> ⚠️ **Importante:** os GPIOs do ESP32 não devem ser tratados como saídas de potência. O resistor em série com cada LED é obrigatório para limitar a corrente.

---

## 📁 Estrutura do repositório

```text
IOT-ESP32-Sala-Inteligente/
│
├── Atuador_LED/
│   └── Código do ESP32 responsável pelo
│       recebimento dos comandos MQTT
│       e controle dos 4 LEDs
│
├── Sensor_de_luz/
│   └── Código do ESP32 responsável pela
│       leitura do LDR e publicação
│       dos dados no broker MQTT
│
└── README.md
```

---

## ▶️ Como executar

### 1. Clonar o repositório

```bash
git clone https://github.com/SEU_USUARIO/IOT-ESP32-Sala-Inteligente.git
```

Entre na pasta do projeto:

```bash
cd IOT-ESP32-Sala-Inteligente
```

### 2. Abrir os projetos

Abra os respectivos arquivos `.ino` utilizando a **Arduino IDE**:

* `Atuador_LED/`
* `Sensor_de_luz/`

### 3. Configurar a rede Wi-Fi

Em **ambos os códigos**, configure as credenciais da rede:

```cpp
#define WIFI_SSID "SUA_REDE"
#define WIFI_PASSWORD "SUA_SENHA"
```

### 4. Configurar o MQTT

Configure os dados necessários para conexão com o broker **HiveMQ**, incluindo:

* Endereço do broker;
* Porta MQTT;
* Usuário;
* Senha;
* Tópicos utilizados pelo Sensor e pelo Atuador.

> 🔐 **Recomendação:** não publique senhas reais do Wi-Fi ou MQTT diretamente no repositório. Para o GitHub, utilize variáveis de configuração locais ou um arquivo que esteja incluído no `.gitignore`.

### 5. Configurar a placa

Na Arduino IDE:

1. Selecione **ESP32 Dev Module**;
2. Selecione a porta COM correspondente ao ESP32;
3. Configure a velocidade de upload conforme necessário.

### 6. Fazer o upload

Faça o upload dos projetos separadamente:

**ESP32 1 — Sensor**

```text
Sensor_de_luz/
        ↓
ESP32 Sensor
```

**ESP32 2 — Atuador**

```text
Atuador_LED/
        ↓
ESP32 Atuador
```

### 7. Monitorar a execução

Abra o **Monitor Serial** da Arduino IDE e utilize:

```text
Baud Rate: 115200
```

O monitor permite acompanhar:

* Conexão com o Wi-Fi;
* Conexão com o broker MQTT;
* Valores capturados pelo LDR;
* Cena identificada;
* Mensagens MQTT publicadas;
* Mensagens MQTT recebidas;
* Estado dos LEDs;
* Confirmações enviadas pelo Atuador.

---

## 📡 Comunicação MQTT

O sistema utiliza o protocolo **MQTT** para comunicação entre o ESP32 Sensor e o ESP32 Atuador.

O fluxo de mensagens segue o modelo:

```text
Sensor
   │
   │ Publica cena
   ▼
MQTT Broker
   │
   │ Entrega mensagem
   ▼
Atuador
   │
   │ Executa cena
   ▼
LED correspondente
   │
   │ Publica confirmação
   ▼
MQTT Broker
```

---

## 💡 Níveis de iluminação

O valor obtido pelo LDR é analisado pelo ESP32 Sensor e convertido em um dos níveis de iluminação definidos pelo projeto.

```text
Luminosidade
     │
     ▼
┌───────────────┐
│ Leitura do LDR│
└───────┬───────┘
        │
        ▼
┌───────────────────┐
│ Classificação     │
│ da luminosidade   │
└─────────┬─────────┘
          │
     ┌────┴────┐
     ▼    ▼    ▼    ▼
   Nível Nível Nível Nível
     1    2    3    4
     │    │    │    │
     ▼    ▼    ▼    ▼
   LED1 LED2 LED3 LED4
```

Os limites matemáticos utilizados para definir cada nível são determinados no firmware do **ESP32 Sensor**.

---

## 🚀 Próximas implementações

Para ampliar o sistema e melhorar a análise dos dados, estão previstas as seguintes funcionalidades:

### 📊 Dashboard interativo

Desenvolvimento de uma interface web ou mobile para:

* Visualizar o estado atual dos LEDs;
* Acompanhar as cenas em tempo real;
* Exibir informações do sensor;
* Monitorar o estado da comunicação MQTT.

### 📈 Gráficos de telemetria

Implementação de gráficos contendo o histórico da luminosidade captada pelo sensor.

Exemplo:

```text
Luminosidade
     │
     │        ╭──╮
     │    ╭───╯  ╰──╮
     │ ───╯         ╰────
     │
     └──────────────────────
             Tempo
```

### ⏱️ Análise do tempo de ativação

Registrar quanto tempo cada cena permanece ativa durante o dia, permitindo calcular:

* Tempo médio de ativação;
* Tempo total por nível;
* Frequência de acionamento;
* Distribuição das cenas ao longo do dia.

### ☀️ Métricas de luminosidade

Criar métricas para analisar o comportamento da luminosidade no ambiente, como:

* Média de luminosidade;
* Valor mínimo;
* Valor máximo;
* Horários de maior luminosidade;
* Horários de menor luminosidade;
* Distribuição dos níveis de iluminação.

---

## 👥 Colaboradores

| Colaborador                     | Contribuição                                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------------- |
| **Ruan Pablo de Lima Pereira**  | Desenvolvimento do firmware de leitura do sensor e calibração dos limiares matemáticos de luz      |
| **Rodrigo Bonifácio Conceição** | Implementação da lógica do atuador, controle dos 4 LEDs e integração da confirmação de estado MQTT |
| **Vinicius Clemente Negherbon** | Estruturação do repositório, arquitetura MQTT, integração dos módulos e testes de comunicação      |
| **Bianca Barp**                 | Documentação do projeto, montagem dos divisores de tensão e diagrama de ligação                    |
| **Guilherme Pietro**            | Testes de carga na rede, ajustes de reconexão Wi-Fi e preparação da demonstração                   |

---

## 📄 Licença

Este é um **projeto acadêmico** e, atualmente, não possui uma licença de software específica definida.

---

## 🎓 Projeto acadêmico

Projeto desenvolvido como atividade acadêmica envolvendo conceitos de:

* Internet das Coisas (IoT);
* Sistemas embarcados;
* ESP32;
* Sensores e atuadores;
* Comunicação Wi-Fi;
* Protocolo MQTT;
* Comunicação JSON;
* Automação;
* Arquitetura distribuída.
