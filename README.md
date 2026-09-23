# 💡 IOT-ESP32-Luminosidade-Plantas

Repositório referente ao projeto de **Internet das Coisas (IoT)** desenvolvido com **ESP32**, focado em solucionar o problema de exposição solar inadequada no cultivo de plantas.

O sistema utiliza um **sensor de luz LDR** para medir a intensidade luminosa do ambiente e, atualmente, aciona um **painel de 4 LEDs indicadores** como alerta. Como evolução do projeto, está planejada a implementação de uma **sombra motorizada utilizando um servomotor**, capaz de atuar fisicamente no ambiente quando forem identificados níveis extremos de luminosidade.

O projeto utiliza comunicação **Wi-Fi + MQTT**, com o **HiveMQ** atuando como broker, mantendo o módulo responsável pela leitura do sensor fisicamente separado do módulo responsável pelo acionamento.

---

## 📋 Sobre o projeto e problema solucionado

O objetivo é desenvolver um sistema IoT desacoplado para auxiliar na proteção de plantas sensíveis, que podem sofrer danos, queimaduras nas folhas e desidratação quando expostas a níveis excessivos de luz e calor provenientes da exposição solar direta.

O sistema foi desenvolvido considerando dois estágios principais:

### 🌱 Estágio atual — Monitoramento e alerta

O sistema monitora continuamente a intensidade luminosa do ambiente.

O **ESP32 Sensor** realiza a leitura do LDR, processa o valor obtido, classifica a luminosidade em uma das **4 cenas de luz** e publica essa informação no broker MQTT.

O **ESP32 Atuador** recebe a cena correspondente e aciona o LED relacionado ao nível de luminosidade detectado, permitindo uma identificação visual do estado atual do ambiente.

### ☀️ Ação física — Em desenvolvimento

Como próxima evolução do projeto, será implementado um **servomotor no Nó Atuador**.

Quando a cena correspondente à **luminosidade extrema** for detectada, o servomotor deverá movimentar uma cobertura física, criando uma área de sombra sobre a planta e reduzindo sua exposição direta à luz solar.

---

## 🔄 Fluxo do sistema — Atual e futuro

```text
┌─────────────────┐
│   Sensor LDR    │
│                 │
│  ESP32 Sensor   │
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
└────────┬────────┘
         │
         ├──► Painel 4 LEDs
         │    Monitoramento visual
         │    ✅ Implementado
         │
         └──► Servomotor
              Sombra física
              🚧 Em desenvolvimento
```

---

## 🏗️ Arquitetura do sistema

Para garantir que o projeto cumpra a premissa de uma aplicação IoT distribuída, e não apenas uma automação local, o sistema possui dois módulos ESP32 fisicamente separados, interligados através da comunicação Wi-Fi e do protocolo MQTT.

### 📡 Módulo Sensor — ESP32 1

Responsável por:

* Realizar a leitura do sensor LDR;
* Processar os valores de luminosidade;
* Classificar a luminosidade nas 4 cenas definidas pelo projeto;
* Conectar-se à rede Wi-Fi;
* Publicar os dados no broker MQTT;
* Estruturar as informações utilizando **JSON**.

### 💡 Módulo Atuador — ESP32 2

Responsável por:

* Conectar-se ao broker MQTT;
* Escutar os tópicos de comando;
* Interpretar as mensagens recebidas;
* Desligar o LED correspondente à cena anterior;
* Acionar o LED da nova cena recebida;
* Publicar uma confirmação do estado executado no broker MQTT;
* **Futuramente**, controlar o servomotor responsável pela movimentação da sombra.

### 🔗 Comunicação

A comunicação entre os módulos ocorre através do seguinte fluxo:

**ESP32 Sensor → Wi-Fi → MQTT HiveMQ → Wi-Fi → ESP32 Atuador**

As mensagens são estruturadas utilizando **JSON**, permitindo uma comunicação organizada e facilitando futuras expansões do sistema.

---

## ⚠️ Precauções de hardware e instalação

### 🔌 Sensibilidade do ESP32

O **ESP32 trabalha com lógica de 3,3 V** e possui limitações elétricas que devem ser respeitadas durante a montagem do circuito.

Por isso, é necessário ter atenção especial à alimentação, corrente e tensão aplicadas aos seus GPIOs.

### 🔩 Resistores obrigatórios

Utilize resistores adequados:

* No divisor de tensão utilizado pelo LDR;
* Em série com cada LED;
* Em qualquer outro circuito que necessite de limitação de corrente.

Nunca conecte um LED diretamente a um GPIO do ESP32 sem um resistor de limitação de corrente.

Durante a prototipagem deste projeto, uma ligação incorreta acabou inutilizando o pino **D13**, reforçando a importância de conferir as conexões antes de energizar o circuito.

> ⚠️ **Importante:** os GPIOs do ESP32 não devem ser utilizados como saídas de potência. O uso correto dos resistores é fundamental para evitar danos aos componentes.

### 🔌 Drivers USB

Dependendo do modelo da placa ESP32 utilizada, pode ser necessário instalar manualmente o driver correspondente ao conversor USB/Serial, como o **CP2102**, para que a placa seja reconhecida corretamente pelo Windows e sua porta COM fique disponível na Arduino IDE.

---

## 📁 Estrutura do repositório

```text
IOT-ESP32-Luminosidade-Plantas/
│
├── Atuador_LED/
│   └── Código do ESP32 receptor
│       Controle atual dos LEDs indicadores
│       e confirmação MQTT
│
├── Sensor_de_luz/
│   └── Código do ESP32 publicador
│       Leitura do LDR e envio de telemetria
│
└── README.md
```

---

## ▶️ Como executar

### 1. Clonar o repositório

```bash
git clone https://github.com/SEU_USUARIO/IOT-ESP32-Luminosidade-Plantas.git
```

Entre na pasta:

```bash
cd IOT-ESP32-Luminosidade-Plantas
```

### 2. Abrir os projetos

Abra os arquivos `.ino` na **Arduino IDE**:

* `Atuador_LED/`
* `Sensor_de_luz/`

### 3. Configurar a rede Wi-Fi

Em ambos os códigos, configure as credenciais da rede:

```cpp
#define WIFI_SSID "SUA_REDE"
#define WIFI_PASSWORD "SUA_SENHA"
```

### 4. Configurar o MQTT

Configure os dados necessários para conexão com o **HiveMQ**:

* Endereço do broker;
* Porta MQTT;
* Usuário;
* Senha;
* Tópicos utilizados pelo Sensor;
* Tópicos utilizados pelo Atuador.

> 🔐 **Recomendação:** não publique senhas reais do Wi-Fi ou MQTT no repositório. Utilize configurações locais ou arquivos incluídos no `.gitignore`.

### 5. Configurar a placa

Na Arduino IDE:

1. Selecione **ESP32 Dev Module**;
2. Selecione a porta COM correspondente;
3. Verifique se o driver USB/Serial necessário está instalado.

### 6. Fazer o upload

Faça o upload de cada firmware para sua respectiva placa física.

**ESP32 Sensor:**

```text
Sensor_de_luz/
        ↓
ESP32 Sensor
```

**ESP32 Atuador:**

```text
Atuador_LED/
        ↓
ESP32 Atuador
```

### 7. Monitorar a execução

Abra o **Monitor Serial** da Arduino IDE utilizando:

```text
Baud Rate: 115200
```

É possível acompanhar:

* Conexão com o Wi-Fi;
* Conexão com o broker MQTT;
* Valores capturados pelo LDR;
* Classificação das cenas;
* Mensagens MQTT publicadas;
* Mensagens MQTT recebidas;
* Estado dos LEDs;
* Confirmações enviadas pelo Atuador.

---

## 📡 Comunicação MQTT

O sistema utiliza o protocolo **MQTT** para realizar a comunicação entre o ESP32 Sensor e o ESP32 Atuador.

O fluxo atual de mensagens é:

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

A utilização do MQTT permite manter o Sensor e o Atuador desacoplados, possibilitando que novos dispositivos sejam adicionados futuramente ao sistema sem a necessidade de alterar diretamente a comunicação entre os dois ESP32.

---

## 💡 Níveis de luminosidade

O valor obtido pelo LDR é processado pelo **ESP32 Sensor** e classificado em uma das quatro cenas de luminosidade definidas pelo projeto.

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
   Cena Cena Cena Cena
     1    2    3    4
     │    │    │    │
     ▼    ▼    ▼    ▼
   LED1 LED2 LED3 LED4
```

Os limites matemáticos utilizados para determinar cada cena são definidos no firmware do **ESP32 Sensor**.

A cena correspondente à maior intensidade luminosa será utilizada futuramente como condição para acionamento da **sombra motorizada**.

---

## 🚀 Próximas implementações

O projeto está estruturado para receber melhorias voltadas à automação física, monitoramento e escalabilidade.

### ☀️ Sombra motorizada — Prioridade

Implementação de um **servomotor** conectado ao ESP32 Atuador.

A funcionalidade deverá:

* Integrar a biblioteca `ESP32Servo`;
* Adicionar o controle do servomotor ao firmware `Atuador_LED.ino`;
* Criar a estrutura física da cobertura;
* Detectar a cena de luminosidade extrema;
* Acionar o servomotor automaticamente;
* Movimentar a cobertura para criar sombra sobre a planta.

Fluxo esperado:

```text
LDR
 │
 ▼
Luminosidade extrema
 │
 ▼
ESP32 Sensor
 │
 │ MQTT
 ▼
MQTT Broker
 │
 │ MQTT
 ▼
ESP32 Atuador
 │
 ▼
Servomotor
 │
 ▼
Cobertura
 │
 ▼
Sombra sobre a planta
```

### 🐳 Dockerização do MQTT

Como implementação futura, está prevista a **dockerização do broker MQTT**, substituindo a utilização do HiveMQ externo por um broker MQTT executado em um **container Docker**.

Essa etapa terá como objetivos:

* Executar o broker de forma local e isolada;
* Facilitar a reprodução do ambiente do projeto;
* Reduzir a dependência de serviços externos;
* Facilitar a implantação em diferentes ambientes;
* Centralizar a infraestrutura de comunicação em containers.

A arquitetura futura poderá seguir o modelo:

```text
┌─────────────────┐
│  ESP32 Sensor   │
└────────┬────────┘
         │
         │ Wi-Fi / MQTT
         ▼
┌──────────────────────────┐
│       Docker Host        │
│                          │
│  ┌────────────────────┐  │
│  │    MQTT Broker     │  │
│  │    Container       │  │
│  └────────────────────┘  │
│                          │
└────────────┬─────────────┘
             │
             │ MQTT
             ▼
┌─────────────────┐
│  ESP32 Atuador  │
└─────────────────┘
```

### 📊 Dashboard interativo

Criação de uma interface web ou mobile para:

* Visualizar a intensidade luminosa;
* Acompanhar a cena atual;
* Visualizar o estado dos LEDs;
* Monitorar o acionamento da sombra;
* Acompanhar os dados em tempo real.

### 🔌 Integração híbrida — Opcional

Estudo da utilização de um **Arduino Uno auxiliar**, conectado ao ESP32 através de comunicação serial **TX/RX**.

A proposta seria utilizar o Arduino como controlador auxiliar para determinadas cargas, enquanto o ESP32 permaneceria responsável pela comunicação Wi-Fi/MQTT e pela telemetria.

Essa arquitetura será avaliada conforme os requisitos elétricos e de controle do servomotor.

---

## 👥 Colaboradores

| Colaborador                     | Contribuição                                                                           |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| **Ruan Pablo de Lima Pereira**  | Desenvolvimento do firmware de leitura do sensor e calibração dos limiares de luz      |
| **Rodrigo Bonifácio Conceição** | Lógica do atuador, controle dos 4 LEDs e integração de estado MQTT                     |
| **Vinicius Clemente Negherbon** | Estruturação do repositório, arquitetura MQTT, integração dos módulos e testes de rede |
| **Bianca Barp**                 | Documentação, montagem dos divisores de tensão e diagrama elétrico                     |
| **Guilherme Pietro**            | Testes de carga na rede, reconexão Wi-Fi e preparação da demonstração                  |

---

## 📄 Licença

Este é um **projeto acadêmico** e, atualmente, não possui uma licença de software específica definida.
