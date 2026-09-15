# Roteiro da apresentação

Anotações para não esquecer nada na hora. A nota depende de mostrar as coisas
funcionando, então o foco aqui é o que precisa aparecer na tela.

## Antes de começar

Rodar `python backend/simulator.py --backfill 12` antes da apresentação, para o
gráfico já ter histórico. Gráfico com três pontos não convence ninguém.

Testar a conexão do Wokwi na rede do lugar onde vai ser a apresentação. É comum
a rede da faculdade bloquear a porta 1883, e descobrir isso na hora é ruim.

Deixar quatro terminais abertos e posicionados: Mosquitto, backend, frontend e um
`mosquitto_sub` acompanhando as mensagens.

Fazer o push para o GitHub e deixar o repositório aberto numa aba.

## Ordem para subir as coisas

1. Mosquitto (porta 1883)
2. InfluxDB (porta 8086)
3. Backend (porta 8000)
4. Frontend (porta 5173)
5. Iniciar a simulação no Wokwi

Ou só rodar `.\scripts\start-all.ps1`.

Atenção: o instalador do Mosquitto no Windows cria um serviço que sobe sozinho
com a configuração padrão dele, sem o listener WebSocket. Se quiser usar a
configuração do repositório, é preciso parar esse serviço antes e subir o
Mosquitto na mão.

## O que mostrar em cada parte

### O problema e a solução

Explicar o cenário em mais ou menos um minuto e mostrar o diagrama da
arquitetura. A frase que resume o projeto: o sensor é independente do servidor
monitorado, então ele continua reportando justamente quando o servidor cai.

### O dispositivo no Wokwi

Deixar a simulação rodando com o ESP32 e o DHT22 visíveis, com o Serial Monitor
aberto mostrando a conexão no WiFi e as publicações.

A melhor parte é mexer no slider do DHT22 ao vivo para subir a temperatura e
mostrar os LEDs mudando de verde para amarelo e depois vermelho, com o buzzer
tocando no crítico.

### MQTT e Mosquitto

Mostrar o Mosquitto rodando e deixar um terminal com:

```
mosquitto_sub -h localhost -t "eyewatcher/#" -v
```

As mensagens vão aparecendo ao vivo durante toda a apresentação, o que já mostra
o MQTT funcionando sem precisar explicar muito.

A demonstração mais forte é parar a simulação do Wokwi e o dashboard mudar para
offline sozinho, por causa do Last Will. Vale guardar isso para o final.

Mostrar também o arquivo `infra/mosquitto/config/mosquitto.conf`.

### Backend em Python

Deixar os logs do backend visíveis, mostrando cada mensagem chegando e sendo
gravada. Abrir a documentação automática em http://localhost:8000/docs e executar
alguma rota ali mesmo.

Se pedirem para ver código, `app/mqtt_client.py` é o melhor lugar: dá para mostrar
a validação da mensagem e o recálculo do estado.

### InfluxDB

Abrir http://localhost:8086 e ir no Data Explorer. Rodar:

```flux
from(bucket: "rack_metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "ambiente")
  |> filter(fn: (r) => r._field == "temperature")
```

Mostrar as tags no painel do lado e explicar por que série temporal em vez de
banco relacional (está em ARQUITETURA.md).

### Dashboard

Mostrar os cards de indicador, o gráfico com as linhas de limite, trocar o
período e apontar a tabela de alertas. Enquanto isso o gráfico vai atualizando
sozinho, porque o WebSocket está recebendo as leituras novas.

Se perguntarem do TypeScript, abrir `src/types/api.ts` e rodar
`npx vue-tsc --noEmit` ao vivo.

## Sugestão de tempo

| Quando | O quê |
|---|---|
| 0 a 1 min | O problema, com o diagrama |
| 1 a 2 min | Wokwi e o Serial Monitor |
| 2 a 3 min | Terminal com as mensagens MQTT chegando |
| 3 a 4 min | Backend e a documentação da API |
| 4 a 5 min | InfluxDB no Data Explorer |
| 5 a 7 min | Dashboard, gráfico e alertas |
| 7 a 8 min | Subir a temperatura no Wokwi e mostrar tudo reagindo |
| 8 a 9 min | Parar o Wokwi e mostrar o offline pelo Last Will, depois o GitHub |

## Se o Wokwi não conectar

Não ficar mexendo no firmware na frente do avaliador. A saída é dizer que a rede
do local bloqueia a porta do broker e que a demonstração vai ser com o publicador
equivalente em Python, que usa o mesmo tópico e o mesmo formato de mensagem:

```
python backend/simulator.py --stress
```

Depois mostrar o Wokwi rodando e publicando no Serial Monitor, mesmo sem alcançar
o broker, para deixar claro que o firmware funciona. O resto da apresentação
continua igual.
