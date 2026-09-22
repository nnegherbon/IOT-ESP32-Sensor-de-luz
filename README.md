# IOT-ESP32-Sensor-de-som

Repositório referente ao projeto de IoT com **ESP32**, utilizando um **sensor de som** para captar variações sonoras do ambiente e acionar um **atuador (LED)** como resposta.

## 📋 Sobre o projeto

O objetivo do projeto é integrar um microcontrolador ESP32 a um sensor de som, de forma que o sistema:

1. Capture o sinal sonoro do ambiente através do sensor;
2. Processe esse sinal no ESP32;
3. Acione um atuador (LED) de acordo com o nível de som detectado.

## 🛠️ Componentes utilizados

- Placa ESP32
- Módulo sensor de som
- LED (atuador)
- Protoboard e jumpers
- Arduino IDE

## 📁 Estrutura do repositório

```
IOT-ESP32-Sensor-de-som/
├── Atuador_LED/     # Código responsável por controlar o LED conforme o sinal recebido
└── Sensor_de_luz/   # Código responsável pela leitura do sensor e envio dos dados
```

## ▶️ Como executar

1. Clone o repositório:
   ```bash
   git clone https://github.com/nnegherbon/IOT-ESP32-Sensor-de-som.git
   ```
2. Abra os arquivos `.ino` na Arduino IDE.
3. Selecione a placa **ESP32** e a porta correta em *Ferramentas*.
4. Faça o upload do código para a placa.
5. Monitore o funcionamento pelo Monitor Serial.

## 👥 Colaboradores

Divisão do trabalho entre os membros do grupo:

| Nome | Contribuição |
|------|--------------|
| **Ruan Pablo de Lima Pereira** | Desenvolvimento do firmware de leitura do sensor de som e calibração dos limites de detecção |
| **Rodrigo Bonifácio Conceição** | Implementação da lógica do atuador (LED), definindo as respostas de acordo com o sinal captado |
| **Vinicius Clemente Negherbon** | Estruturação do repositório, integração dos módulos e testes de comunicação com o ESP32 |
| **Bianca Barp** | Documentação do projeto, montagem do circuito e diagrama de ligação dos componentes |
| **Guilherme Pietro** | Testes de funcionamento, ajustes finais e preparação da apresentação do projeto |

> Sinta-se livre para ajustar as descrições acima caso alguém tenha feito algo diferente do que está listado — a divisão foi feita apenas para fins de organização do trabalho em grupo.

## 📄 Licença

Projeto acadêmico, sem licença específica definida.
