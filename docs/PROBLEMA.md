# O problema e a solução proposta

## Onde está o problema

Servidor de laboratório, de empresa pequena ou o servidor caseiro de quem mexe
com isso por hobby raramente fica numa sala preparada. Na prática ele acaba num
almoxarifado adaptado, numa sala de apoio ou até dentro de um armário. São
lugares onde a temperatura varia bastante ao longo do dia e onde o ar-condicionado
costuma ser desligado fora do horário comercial.

A falha que acontece nesses casos segue quase sempre o mesmo roteiro. A
temperatura dentro do rack sobe devagar, ao longo de horas. O processador começa
a reduzir a frequência para se proteger e o desempenho cai, sem que ninguém
perceba. Depois algum componente, geralmente a fonte ou um disco, atinge a
temperatura de desligamento automático. Aí o serviço cai, e só nesse momento
alguém vai descobrir que existia um problema térmico.

Dois detalhes tornam isso pior do que parece.

O primeiro é que o problema é percebido pelo sintoma e não pela causa. Quando
alguém nota, o estrago já aconteceu. E mesmo quando não chega a cair, o calor
acima da faixa recomendada vai reduzindo a vida útil dos componentes de forma
silenciosa e acumulada.

O segundo é que não sobra histórico nenhum. Sem uma série de medições ao longo do
tempo não dá para responder perguntas básicas depois do problema: a temperatura
já estava subindo antes da queda de ontem? O pico acontece sempre no mesmo
horário, por causa do sol da tarde naquela parede? O ar-condicionado realmente
ficou ligado no fim de semana? A troca do ventilador melhorou alguma coisa ou foi
impressão?

Vale mencionar a umidade também, porque quase ninguém mede. Umidade muito baixa
favorece descarga eletrostática e umidade muito alta favorece corrosão e
condensação.

## Por que as opções atuais não resolvem

Termômetro de parede mostra o valor naquele instante e só. Não registra nada e
depende de alguém olhando na hora certa.

Os sensores da própria placa, acessíveis pela BIOS ou por IPMI, medem a
temperatura do chip e não a do ar dentro do rack. Além disso não cobrem umidade
e ficam indisponíveis exatamente quando o servidor cai, que é quando a informação
seria mais útil.

Sistemas comerciais de monitoramento de datacenter resolvem o problema, mas têm
custo e complexidade que não fazem sentido nesse porte.

Planilha preenchida à mão funciona no papel, mas a frequência de medição fica
baixa demais e as pessoas esquecem.

Sobra uma lacuna: falta uma medição contínua, feita por um equipamento que não
seja o próprio servidor monitorado. É esse tipo de coisa que a Internet das
Coisas resolve bem.

## O que o eyeWatcher faz

O eyeWatcher mede temperatura e umidade dentro do rack a cada 5 segundos, guarda
tudo e mostra num dashboard web.

O ponto central do projeto é o dispositivo de medição ser independente do servidor
monitorado. Mesmo que o servidor esteja desligado, travado ou superaquecido, o
ESP32 continua medindo e reportando normalmente. É justamente nesse momento que a
informação vale mais.

O caminho do dado é o seguinte:

```
ESP32 + DHT22  --MQTT-->  Mosquitto  -->  Python  -->  InfluxDB  -->  Dashboard Vue
```

O ESP32 lê o sensor, classifica o estado e publica um JSON num tópico MQTT. O
Mosquitto entrega para o backend em Python, que valida a mensagem, recalcula a
classificação e grava no InfluxDB. O dashboard consulta esse histórico e também
recebe as leituras novas em tempo real.

### Ligando as dores nas funcionalidades

Para o problema de só descobrir tarde demais, o sistema lê a cada 5 segundos e
classifica na hora em normal, alerta ou crítico. A sinalização aparece tanto nos
LEDs do próprio rack quanto no topo do dashboard.

Para a falta de histórico, todas as leituras ficam guardadas no InfluxDB por 30
dias, e o gráfico permite olhar de 15 minutos até 7 dias atrás.

Para a umidade ignorada, o mesmo sensor DHT22 já mede, com faixa segura e limites
próprios.

Para a dúvida de "melhorou ou foi impressão", existe o painel com mínima, média e
máxima do período, que permite comparar antes e depois de uma mudança com número
em vez de achismo.

E para o caso do sensor parar de reportar, o MQTT tem o recurso de Last Will: se
o dispositivo cair, o próprio broker publica que ele está offline. Assim a falta
de dado também vira um aviso, em vez de o dashboard ficar mostrando para sempre a
última leitura boa.

## Por que MQTT e não HTTP direto

MQTT é o protocolo mais usado em IoT e por bons motivos neste caso.

Ele é leve, o que importa num microcontrolador. Usa uma conexão TCP que fica
aberta, em vez de abrir uma requisição nova a cada leitura. Tem confirmação de
entrega quando você precisa dela. E separa quem publica de quem consome, então dá
para reiniciar o backend sem que o ESP32 precise saber ou ser reconfigurado.

O Last Will, que avisa da queda do dispositivo sem custo nenhum, não tem
equivalente direto em HTTP.

## Por que um banco de séries temporais

As leituras formam um fluxo que só cresce, indexado por tempo, e que quase sempre
é consultado por intervalo e de forma agregada. O tipo de pergunta é "média por
minuto nas últimas 6 horas", não "traga a linha com esse id".

O InfluxDB é feito para esse padrão. Ele comprime bem dado numérico repetitivo,
já tem agregação por janela de tempo embutida e aplica política de retenção
sozinho. As três coisas dariam trabalho manual num banco relacional.

## O que entra neste bimestre

- Um dispositivo ESP32 simulado no Wokwi com sensor DHT22
- Publicação por MQTT, com Last Will configurado
- Mosquitto como broker, com porta TCP e WebSocket
- Backend em Python que recebe, valida e grava as leituras
- Persistência no InfluxDB com tags e campos modelados
- API REST e WebSocket para o histórico e o tempo real
- Dashboard em Vue 3 com TypeScript, Vite e gráfico em Chart.js
- Código versionado no Git

## Para onde isso vai no próximo bimestre

O projeto foi montado para crescer sem precisar reescrever.

Os tópicos MQTT já usam o formato `eyewatcher/<rack>/...` e o backend já assina
com curinga, então colocar um segundo rack não exige mudar código.

Além disso a ideia é acrescentar notificação ativa por e-mail ou Telegram quando
o estado ficar crítico por algumas leituras seguidas, login de usuário no
dashboard com senha no Mosquitto, sensor de corrente e de porta aberta
reaproveitando o mesmo formato de mensagem, e uma regressão simples sobre o
histórico para estimar quando a temperatura vai cruzar o limite e avisar antes.
