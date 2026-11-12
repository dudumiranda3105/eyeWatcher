# Roteiro da apresentação (16/11/2026)

Sem slides: o grupo apresenta a aplicação funcionando, nesta ordem.

## Antes de chegar na sala

- Rode `docker compose up` em casa pelo menos uma vez, com internet. A imagem do
  Ollama e o modelo de 2 GB precisam já estar baixados.
- Confira `secrets/CREDENCIAIS.txt`.
- Na sala, suba tudo uns 5 minutos antes: o LLM demora para carregar na memória.
  A página Assistente mostra "Modelo pronto" quando estiver no ponto.

## 1. Subir tudo

```bash
docker compose up -d
```

```bash
docker compose ps
```

Mostrar todos os containers `healthy`. Os serviços `bootstrap` e `ollama-pull`
terminam e saem, e isso é o esperado.

## 2. Login e os três papéis

Abrir http://localhost:8080. Entrar como `visualizador` e mostrar que não há botões
de comando. Entrar como `operador` e mostrar que eles aparecem, mas que o Laboratório
não deixa gerar. Entrar como `administrador` e mostrar a Auditoria.

## 3. Simulador e MQTT

Ver as mensagens passando pelo Mosquitto:

```bash
docker compose exec mosquitto sh -c 'mosquitto_sub -u gateway -P "$(cat /run/eyewatcher/gateway)" -t "eyewatcher/+/+/+/telemetry" -C 5 -v'
```

## 4. API REST

Abrir http://localhost:8080/api/docs.

## 5. Mensageria e o consumidor parado

Abrir a página Mensageria e mostrar filas, consumidores e taxas. Depois:

```bash
docker compose stop recorder
```

A fila `q.telemetry.influx` cresce e o consumidor dela fica em zero. Depois:

```bash
docker compose start recorder
```

A fila esvazia. Clicar em "Publicar mensagem inválida" e mostrar a mensagem na DLQ.

## 6. Bancos

Página Serviços. No InfluxDB, mostrar o bucket `telemetry`. No Adminer, mostrar as
tabelas `devices`, `rules` e `audit_log`. No Dashboard, trocar o período do histórico.

## 7. Dashboard em tempo real

Mostrar os indicadores mudando sozinhos e o histórico crescendo.

## 8. Regra automática e controle pela Web

Ligar a iluminação no Dashboard: a luminosidade sobe. Desligar os dois CRACs: em
cerca de 30 segundos a temperatura passa de 35 °C e o exaustor liga sozinho. Ligar os
CRACs de novo.

## 9. Laboratório de dados

Mostrar os parâmetros e clicar em Gerar dados. Com o padrão são cerca de 4 milhões de
leituras. Falar que a API não trava, porque o job roda pela fila.

## 10. Treinamento

Clicar em Treinar modelos. Mostrar MAE, RMSE e R², a comparação com a base simples, o
gráfico de previsto contra real e a importância dos atributos. Mostrar que a versão
em uso mudou sem reiniciar nada.

## 11. Falha injetada

Em Insights, escolher "Desgaste de rolamento" no `crac-01` e clicar em Injetar falha.
Em cerca de 1 minuto a saúde cai abaixo de 65 e abre o alerta. Ir para o Gêmeo digital:
o CRAC fica vermelho e treme mais. O `crac-02` continua saudável.

## 12. Assistente

Perguntar:

- Qual equipamento está com a pior saúde?
- O que significa esse alerta e o que devo fazer?
- Explique as métricas do último treino em palavras simples.
- Por que vocês usam Mosquitto e RabbitMQ?

## Perguntas que podem aparecer

**Por que dois brokers?** MQTT é leve para o dispositivo e tem Last Will. O RabbitMQ
dá filas, roteamento e DLQ entre os serviços.

**Como o modelo não "cola"?** Os rótulos só existem no dataset, as janelas só olham
para trás e a divisão é por equipamento.

**Por que a importância de `hour_sin` é alta?** A temperatura e a corrente têm ciclo
diário. O modelo usa a hora para separar esse ciclo normal da degradação.

**As horas são reais?** Não: cada leitura vale 10 minutos simulados.

**Por que a vida útil erra mais que a saúde?** Máquinas com o mesmo desgaste podem
degradar em ritmos diferentes, então prever quando vai falhar é mais difícil do que
dizer como ela está agora.
