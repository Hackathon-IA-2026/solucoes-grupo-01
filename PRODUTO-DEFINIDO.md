# CurtailLess: definição do produto

> Versão 3, 26/09/2026, madrugada de sábado. O que mudou em relação à versão 2: o número da janela
> passou de um conjunto para a distribuição medida em 136 conjuntos, a conta da bateria foi refeita e
> derrubou o PLD de indiferença de R$ 824 para R$ 1.329, e a coordenação ganhou o procedimento com
> prazo e a distinção entre os dois mecanismos que a norma oferece.

## 1. O produto em uma frase

**O operador publica, todo dia, as horas em que a parada da usina não custa nada. A gente transforma
isso em data no calendário de manutenção, em coordenação com o sistema, e em decisão de bateria.**

## 2. As quatro linhas de valor

O produto é um só, e entrega quatro coisas encadeadas. Cada linha usa o que a anterior produziu.

### 2.1 A previsão com janela, até 30 dias

**O que é.** O mapa do corte e o calendário. A hora do dia, a razão, a classe, a concentração por
conjunto, a safra de ventos, e o ranking das janelas dos próximos 7 a 30 dias por energia cortada
esperada.

**Com que dado.** A base aberta do operador, o PLD da CCEE e a margem hidráulica reconstruída com
insumos previstos.

**Por que se sustenta.** O modelo de 6 h tem AUC de 0,821 no sistema e 0,844 no conjunto, contra 0,636
e 0,694 do baseline de hora do dia. E o horizonte longo não depende do modelo: depende da persistência
medida, que é de 82% das janelas de 72 h com corte em Paulino Neves e 98% em Caju.

### 2.2 O plano de manutenção e o ganho

**O que é.** O ranking das janelas candidatas ordenado pelo ganho de deslocar a intervenção, com a
duração declarada, o custo de O&M separado e o alerta da banda de tolerância.

**Com que dado.** O histórico de corte por conjunto, o padrão horário, o PLD da janela, e o plano de
manutenção da usina, que é privado e entra como parâmetro declarado.

**O ganho, com a derivação na seção 4 e o panorama na seção 5.** A mediana do setor é de **29,7 MWh
por MW por janela de 72 horas**, medida em 136 conjuntos que cobrem 66,8% da capacidade eólica, com o
quartil superior em 37,4 e o p90 em 42,6. Numa usina de 27,6 MW, isso vale de R$ 1.702 a R$ 7.423 por
MW conforme o preço, e o rótulo de teto de previsão perfeita vai em cima.

**Por que é a linha principal.** É a única recorrente, material e independente de aprovação de
terceiros. Nem o regulador, nem o operador, nem o juiz: o corte acontece de qualquer forma, e o
deslocamento é decisão da usina.

### 2.3 A coordenação com o operador

**O que é.** A usina declara a janela de manutenção, e o operador programa sabendo. O produto é o canal
onde o plano privado da usina encontra a janela esperada de corte do sistema.

**O procedimento, e ele tem prazo.** A declaração entra como solicitação de intervenção do Submódulo
4.2, e o aproveitamento é uma categoria dessa solicitação (item 1.1.2 e Anexo B.7). No Programa Mensal
de Intervenções, a antecedência é de **até 15 dias** antes do início; fora dele, o prazo fica **abaixo
de 15 dias e igual ou acima de 48 horas**; e o operador responde **até as 15h do dia anterior** ao
início. O operador publica a caracterização de aproveitamento (item 1.4.3, alínea j).

**Dois mecanismos distintos, e não coincidentes.** Esta é a parte que precisa ficar clara, porque a
diferença decide o que se pode prometer.

| Mecanismo | Quando se aplica | O efeito |
| --- | --- | --- |
| **Aproveitamento, item 3.16** | Intervenção programada durante indisponibilidade **do sistema de transmissão ou de distribuição**, com causa externa ao empreendimento | A indisponibilidade **pode ser desconsiderada do cálculo da TEIP**, se programada e dentro da janela do desligamento principal |
| **Serviço durante o corte, item 5.2.1** | Unidade **já desligada por conveniência operativa** e o agente faz serviço nela | A unidade **passa a ser classificada como indisponível**, mesmo que pudesse voltar imediatamente |

O Anexo 2 define o estado DCO como "Desligado por conveniência operativa do ONS", e esse é o comando
que produz o corte. Ou seja: o item 5.2.1 é exatamente o caso do produto.

**O efeito no registro, e ele tem base na norma.** A Geração de Referência Final é o menor valor entre
a geração de referência e a disponibilidade eletromecânica (RO-AO.BR.13, itens 3.3 e 5.2.2.10), e o
corte não supera a disponibilidade (item 4.6). Então a unidade marcada como indisponível tem a
referência limitada pela disponibilidade, e o corte apurado cai. **O item 3.16 não é o que faz isso**:
ele age sobre a TEIP. São dois efeitos, de duas normas.

**O que a coordenação faz.** Evita a perda dupla, porque a manutenção cai onde a energia já seria
apagada. Reduz o corte exigido do sistema, porque uma usina indisponível encolhe o excedente, e o
operador precisa cortar menos as outras. Reduz o risco de a usina ser pega de surpresa, porque a parada
entra no programa em vez de acontecer por acidente. E abre o ganho do item 3.16 quando a causa externa
for de transmissão ou distribuição, e o do item 5.2.1 sempre que a unidade já estiver em DCO.

**O que ela não faz.** Não evita o corte. O corte é decisão de sistema, tomada pelo balanço e pela
restrição de escoamento, e a coordenação não cria nem cancela corte. Quem prometer evitar o corte perde
a banca na primeira pergunta.

**A ressalva de postura.** O registro de curtailment cai, porque a referência é limitada pela
disponibilidade. A leitura correta é que o excedente do sistema encolheu de verdade, e não que o corte
foi escondido. Se o produto for vendido como redutor do curtailment registrado, ele perde credibilidade
com quem avalia. A venda é a colocação da manutenção, e o efeito no registro é consequência
verificável.

**O detalhe de incentivo.** O ganho privado da usina é a energia cortada da janela. O ganho sistêmico,
de cortar menos as outras, ela não captura. É por isso que a coordenação precisa do operador, e não só
da usina.

### 2.4 A decisão de bateria

**O que é.** Por conjunto, quanto do custo anualizado de uma bateria o corte cobriria, se vale disputar
o leilão e em qual barramento, e o dimensionamento pela profundidade e duração da janela.

**A conta e o veredito estão na seção 6.**

## 3. De onde vem o dado, e o que o operador já tem

| Fonte | O que traz | Como entra |
| --- | --- | --- |
| Portal de Dados Abertos do operador | restrição por conjunto em base horária, geração verificada por usina, o painel de curtailment, a razão nos arquivos `_tm` | ingestão e normalização |
| CCEE | PLD horário, por submercado | ingestão |
| SCADA e medição da usina | a geração real, a disponibilidade, o vento e a irradiância medidos | coletor em paralelo, somente leitura |
| Plano de manutenção da usina | a duração e a restrição de execução de cada intervenção | parâmetro declarado |

O trabalho que ninguém quer fazer: o `id_ons` não é global, o nome do conjunto tem grafia divergente
entre bases, a razão só aparece nos arquivos `_tm`, e boa parte dos nulos é estrutural.

**A objeção correta, e a resposta.** O operador já tem o dado da usina, porque a norma obriga o agente
a enviar a geração verificada, o vento e a irradiância em tempo real. O produto não entrega dado que
falta ao operador. Ele entrega o inverso: a visão do operador de volta para a usina, com razão,
referência, limite e rateio organizados por patamar e por prazo, mais o mecanismo de manutenção que a
usina não tem, porque o plano dela é privado e o operador não tem motivo para otimizá-lo.

**O que não é pilar.** A contestação por dado inválido é a menor das linhas: o dado inválido é de 1,9%
no agente e 8,7% na supervisão na média nacional, e o teto de toda a via de compensação é de R$ 5.379
por MW por ano, ou 9,1% da perda anual. O que sobra de defensável ali é a reclassificação de razão e o
cumprimento do prazo de 3 dias úteis.

## 4. A derivação do ganho da janela

**Passo 1: a energia cortada por janela, no conjunto.** Em janelas de 72 horas do Conj. Paulino Neves,
a mediana é de 1,27 GWh e o melhor caso é de 14,05 GWh, em 245 janelas presentes.

**Passo 2: a fatia da usina no conjunto.** Delta 3 I tem 27,6 MW de 426 MW, ou 6,4789%.

**Passo 3: a energia da usina por janela.** A mediana dá 82 MWh e o melhor caso dá 910 MWh.

**Passo 4: o ganho de escolher a melhor em vez da mediana.** 828 MWh, que valem:

| Janela de 72 h | Energia cortada da usina | A R$ 57,31 | A R$ 150 | A R$ 300 |
| --- | --- | --- | --- | --- |
| melhor caso | 910 MWh | R$ 52.170 | R$ 136.545 | R$ 273.090 |
| mediana | 82 MWh | R$ 4.700 | R$ 12.342 | R$ 24.684 |
| **ganho de escolher bem** | **828 MWh** | **R$ 47.470** | **R$ 124.203** | **R$ 248.406** |

**A leitura obrigatória.** O número é teto de previsão perfeita: supõe que o ranking acerta a melhor
janela. O produto move a usina da mediana na direção do melhor caso, e o que se mede é a captura
realizada. O complemento em tempo real é a banda de tolerância, com o item 4.13 da RO-AO.BR.13
admitindo 5% ou 5 MW entre geração verificada e geração limitada.

## 5. O panorama, e a resposta sobre o caso extremo

**Paulino Neves não é caso extremo.** Rodando a mesma janela de 72 horas em todos os conjuntos com dado
suficiente, ele fica no **46º percentil** do ganho por MW: 62 dos 136 conjuntos medidos rendem mais, e
73 rendem menos. Ele não entra nem no quartil superior.

**O panorama medido, em MWh por MW por janela de 72 horas:**

| Estatística | Ganho por MW |
| --- | --- |
| mediana | 29,7 |
| quartil inferior | 19,8 |
| quartil superior | 37,4 |
| p90 | 42,6 |
| máximo | 61,0 |
| mínimo | 8,5 |
| **Paulino Neves** | **31,1** |

**A cobertura, e o que ficou de fora.** São 179 conjuntos no dado; 136 entraram, cobrindo 26.090 dos
39.085 MW, ou 66,8% da capacidade. Saíram 42 por cobertura insuficiente de dado e 1 por disponibilidade
zerada. Há duplicatas de registro de ponto de conexão, e isso está declarado no relatório.

**A sensibilidade ao horizonte.** Paulino Neves fica no percentil 21 na janela de 24 horas, 26 na de 48,
46 na de 72 e 70 na de 168. Quanto mais longa a janela, menos extremo ele é, e a conclusão não muda.

**O número de manchete recomendado.** A distribuição por MW, e não um conjunto: **mediana de 29,7 MWh
por MW por janela, com o quartil superior em 37,4, medida em 136 conjuntos que cobrem dois terços da
capacidade eólica do país.** É mais honesto que o âncora atual, porque não depende de escolher o
conjunto que conta a melhor história.

## 6. A bateria: a conta, o veredito e a entrega

### 6.1 A cadeia, em fórmulas

O custo anualizado de uma bateria é `CRF(12%, 15 anos) × capex`, e o fator de recuperação é de 0,146824.
Com o capex de R$ 1.742.000 por MWh, o custo anualizado é de **R$ 255.797 por MWh por ano**.

O PLD de indiferença é `custo anualizado ÷ (0,85 × N_eff)`, onde `N_eff` são os ciclos equivalentes por
ano e 0,85 é a eficiência de ida e volta.

**Com `N_eff` de 365, a fórmula dá exatamente R$ 824 por MWh.** E é aí que estava o erro: 365 supõe que
a bateria enche todos os dias do ano. Nenhum conjunto tem corte todos os dias. A mediana é de **286
dias com corte por ano**, o melhor caso é 335 e o pior é 111.

### 6.2 O resultado, com o dimensionamento defensável

O critério adotado: a energia da bateria igual ao corte do dia mediano, e a potência igual a essa
energia dividida por 4 horas. É o critério que não promete absorver tudo.

| Critério | Conjuntos | PLD de indiferença mediano | Faixa |
| --- | --- | --- | --- |
| **dia mediano, potência em 4 h** | **153** | **R$ 1.329** | R$ 1.188 a R$ 1.781 |
| dia no percentil 95 | 166 | R$ 3.131 | mais alto |
| absorver tudo | 153 | R$ 5.859 | capex de cerca de R$ 25 milhões por MW |

Com o critério defensável, `N_eff` mediano é de 226 ciclos e a utilização é de 62%. **Nenhum conjunto
fecha a R$ 824, nem ao teto estrutural de R$ 785,27.** Dois conjuntos de 153 fecham abaixo de R$ 1.200,
e 99% só fecham ao teto horário de R$ 1.611,04.

**Uma correção que precisa ser dita.** A faixa "18% a 73% conforme o conjunto" que circulava no material
não varia por conjunto, varia pelo cenário de preço: 150 dividido por 824 dá 0,18 e 600 dividido por 824
dá 0,73. A cobertura mediana a R$ 250 é de **0,19**.

### 6.3 O veredito

**Contra o corte sozinho, não se paga.** O PLD de indiferença mediano de R$ 1.329 é 5,3 vezes o PLD de
demonstração de R$ 250, e acima do teto estrutural. A bateria fecha em quatro condições, e todas
precisam ser ditas:

1. **Receita fixa de leilão**, de R$ 2,358 milhões por MW por ano para 16% de TIR alavancada, onde a
   mitigação vira serviço de sistema e deixa de depender do PLD.
2. **PLD regular acima de R$ 1.188**, que é o melhor caso medido.
3. **Capex do bloco importado**, de R$ 648 mil por MWh em vez do projeto completo, o que baixa a
   mediana para R$ 494.
4. **Conjuntos com mais de 85% dos dias com corte**, no Nordeste, onde a bateria passa a ser arbitragem
   complementar e não mitigação de corte.

A sensibilidade à duração é pequena: 2, 4 e 8 horas movem a mediana entre R$ 1.322, R$ 1.329 e R$ 1.409.

### 6.4 Como entregamos

**Posição.** Se vale disputar o leilão e em qual barramento. O anexo do edital pontua 129 barramentos
com β de 0,9, e isso vale até 11,1% de folga de receita no lance.

**Dimensionamento.** Pela profundidade vezes a duração da janela, e não pela potência da usina, com o
critério declarado ao lado do número.

**Despacho.** Carregar na janela de corte e devolver no pico da noite. O produto mede as duas pontas.

**A lacuna declarada.** O tratamento do corte com bateria não tem regra publicada, e os procedimentos
têm 180 dias, vencendo em dezembro. A bateria que carrega durante o corte não muda o corte apurado:
muda o destino da energia.

## 7. A janela de manutenção, verificada fora da wiki

**O operador, na projeção dele.** No PEN 2026-2030, apresentado em 07/07/2026, os técnicos do ONS
escrevem: *"O curtailment, principalmente energético, continuará sendo comum na operação do SIN,
ocorrendo com maior frequência entre 7h e 15h, com maior intensidade aos domingos"*. E acrescentam que
o perfil não deve mudar: os cortes caem de 19% das horas em 2027 para 14% em 2030, mas *"seu perfil não
deverá ser alterado"*.

**A agência, num despacho.** Em junho de 2026, o operador pediu às distribuidoras o corte de mil MW
entre 10h e 14h de um domingo.

**A EPE, na nota técnica de indisponibilidade fotovoltaica.** Os empreendedores declaram
indisponibilidade programada zero valendo-se da hipótese de fazer a manutenção à noite, e é isso que
mostra que escolher a hora da manutenção por motivo de métrica já é prática estabelecida.

**A regra brasileira.** O deslocamento é permitido, e o caminho é o Submódulo 4.2 com o item 3.14 do
RO-AO.BR.04, mais o item 3.16 e o item 5.2.1 detalhados na seção 2.3.

**A literatura internacional, com número.** Donnelly e Carroll, em *Ocean Engineering* 2025, medem
redução de 50% de custo operacional contra 20% da manutenção oportunista que só usa gatilho interno.
McMorland e colegas, em *Renewable and Sustainable Energy Reviews* 2023, propõem o quadro OM+ e
registram que a oportunidade *"não havia sido considerada antes na literatura"*. O NREL, em 2014, já
propunha agendar a manutenção na estação de alta disponibilidade.

**O mercado adjacente.** A OxMaint vende agendamento por previsão de tempo, com faixa publicada de
US$ 19 a 49 por usuário por mês, e alega, como fornecedor, que *"menos de 12% dos operadores de usinas
renováveis usam dado de previsão para decidir o agendamento"*. A Amperon vende previsão de curtailment.
Nenhum deles agenda a manutenção **na** janela de corte, e a página da OxMaint sobre curtailment trata o
corte como incontrolável.

**O que não foi encontrado.** Não há caso brasileiro publicado de manutenção de renovável deslocada para
a janela de corte.

## 8. O que a usina ganha, e o que o operador ganha

**A usina** ganha a janela, com o panorama da seção 5; o plano ordenado pelo ganho; a coordenação, com
o prazo e o item da norma; a decisão de bateria com o PLD de indiferença medido por conjunto; e o dado
que o credor e o comprador não têm por ativo.

**O operador** não é cliente, e o pitch não finge que é. Ele ganha o que ele mesmo pediu. No relatório
técnico de 2025 sobre a atribuição, ele admite a iniquidade por escrito: *"os REDs permanecem fora desse
processo de restrição, sobrecarregando os geradores controlados pelo ONS e, potencialmente,
comprometendo a equidade da operação do sistema"*. E quantifica: com rateio proporcional incluindo a
geração distribuída, a energia restrita das fontes centralizadas cairia de 4.330 GWh para 2.315 GWh,
uma redução de 46%. A recomendação formal pede mecanismos para que os REDs participem proporcionalmente
ao impacto no balanço. O produto entrega a medição que essa recomendação pede, e a coordenação que a
programação dele ganha.

**Duas ressalvas de postura.** A iniquidade se cita pelo relatório técnico dele, nunca como acusação. E
o produto não promete o rateio, porque a relatora da agência votou por manter a micro e minigeração
fora da nova regra, e a decisão segue sem desfecho depois de pedido de vista.

## 9. A vantagem, contra o que já existe

| O que existe | O que faz | Por que não é isto |
| --- | --- | --- |
| Previsão de curtailment, como a da Amperon | antecipa o corte para proteger a receita | para na previsão, e não a converte em decisão de manutenção |
| Agendamento por previsão de tempo, como o da OxMaint | põe a manutenção na janela de vento baixo ou de pouca irradiância | a janela é probabilística e ainda custa geração; a de corte é comandada e a energia já está apagada |
| Plataformas de O&M, como Scoop, ONYX e SkySpecs | o fluxo do alarme até a fatura | não conhecem o corte, e o calendário ignora o estado do sistema |
| Ferramentas regulatórias brasileiras, como Areticon e Delfos | o SAGER e o dossiê de contestação | não fazem a janela, nem a atribuição, nem a coordenação |
| Otimizadores de bateria | o despacho do BESS | assumem que a bateria já existe, e não decidem se ela deveria |

**O diferencial, em uma frase.** O produto é o único que liga o registro publicado do operador ao plano
privado da usina, e a coordenação é o único desenho em que isso fica de dois lados, com o item da norma
e o prazo na mão.

**O teste de defesa.** Um concorrente com o mesmo dado público reconstrói isso em uma semana? O
relatório, a previsão e os prazos, sim, então são entrada. O ranking com o plano da usina, a coordenação
com o prazo do Submódulo 4.2 e a decisão de bateria por conjunto, não.

**Por que ninguém está fazendo.** A O&M da usina é terceirizada, e o contrato do terceiro paga por
disponibilidade, não pela hora em que a manutenção acontece. Quem escolhe a janela hoje é o calendário
do fabricante e a conveniência da equipe.

## 10. O que a IA faz

**Prever.** O modelo de 6 h, com AUC de 0,821 e 0,844 contra 0,636 e 0,694 do baseline, e a margem
hidráulica como variável central, com correlação de −0,75 com o corte energético. O caminho para ganhar
antecedência é reconstruir a margem com a carga do DESSEM em D-1 e o vento e a irradiância previstos.

**Normalizar.** O dado do operador chega sujo de forma estrutural: identificador que não é global, nome
de conjunto com grafia divergente, razão que só existe num tipo de arquivo, nulo que é desenho e não
falha, e duplicata de ponto de conexão.

**Redigir.** O relatório vivo da usina, que se congela em dossiê, escrito a partir dos números medidos,
com trava contra número inventado.

**Traduzir a norma.** O Submódulo 4.2 com o Anexo B.7 e os prazos, o RO-AO.BR.04 com os itens 3.14,
3.16 e 5.2.1, o RO-AO.BR.13, a Portaria 140 e a Lei 15.269, com a citação do item ao lado da resposta.
É o fosso mais defensável, e é a parte que a banca consegue verificar na hora.

A fronteira honesta: a IA não inventa regra, não decide a física e não substitui o operador.

## 11. O encaixe no Desafio 1

O enunciado oficial diz: *"Como a IA e a análise de dados podem ajudar a compreender, antecipar ou
enfrentar o curtailment, ampliando o aproveitamento da geração renovável sem comprometer a segurança do
sistema elétrico?"* E acrescenta que os registros vêm *"detalhados por usina, período e categoria"*, e
que os participantes poderão *"identificar padrões, compreender as condições que levam aos cortes e
desenvolver soluções capazes de apoiar a operação do sistema e reduzir seus impactos"*.

| Trecho do enunciado | O que o produto entrega |
| --- | --- |
| compreender | o mapa do padrão: hora, razão, classe, concentração por conjunto, safra de ventos |
| antecipar | o alerta de 6 h e o calendário de janelas dos próximos 7 a 30 dias |
| enfrentar | a orientação com data: onde parar, o que contestar, qual a via, se cabe bateria |
| ampliar o aproveitamento | a usina entrega mais energia no ano porque deixa de parar nas horas boas |
| sem comprometer a segurança | nada aqui manda gerar fora do comando |
| por usina, período e categoria | a atribuição por usina, com período e razão, é o núcleo da medição |
| apoiar a operação do sistema | a medição que a recomendação do próprio operador pede, e a coordenação da manutenção com a janela |
| reduzir seus impactos | a janela, a coordenação e a decisão de bateria, com o ganho em reais |

## 12. O que fica de fora, declarado

1. O produto **não remove o gargalo de transmissão**, e **não cria geração**.
2. O produto **não garante o ressarcimento** e não promete o rateio.
3. A coordenação **não evita o corte**, e o efeito dela no registro precisa da leitura correta.
4. **Não há caso brasileiro publicado** de manutenção deslocada para a janela de corte.
5. **A base da nova apuração não foi publicada**, então a elegibilidade ao acordo é estimada.
6. **O tratamento do corte com bateria não tem regra publicada**, e vence em dezembro.
7. Os cortes devem **cair de 19% das horas em 2027 para 14% em 2030**, na projeção do operador. O que
   sustenta o produto nesse cenário é o perfil não mudar e a janela não depender do volume.
8. **O PLD horário real não foi obtido** (a CCEE responde 403), então as contas de receita usam preço
   constante com premissas declaradas.
9. **A capacidade dos conjuntos foi derivada** do percentil 95 da disponibilidade, validada em três
   conjuntos com erro de até 3,6%.
10. **Não há dado por conjunto para solar**: o recorte por conjunto é eólico, e a solar existe no grão
    de sistema.
11. Um estudo com premissas diferentes, em que a bateria só despacha fora do corte, conclui por payback
    de 40 a 70 anos. Ele não descreve o caso brasileiro e sai do número de manchete.

## 13. O que construir no sábado

**Fechar a medição da janela** com o panorama: a distribuição por MW em 136 conjuntos, com o quartil e
o p90, no lugar do âncora de um conjunto só.

**Fechar o plano de manutenção**, com a duração declarada, o custo de O&M separado e a banda.

**Fechar a bateria** com o PLD de indiferença por conjunto e o critério de dimensionamento declarado.

**Fechar a tela da coordenação**, com os dois mecanismos, o prazo do Submódulo 4.2 e as seis perguntas
ao mentor.

**Fechar as telas na ordem do enunciado**, e o relatório vivo com a seção de normas e a de lacunas.

**Ensaiar a abertura**, que começa pelo padrão e pela janela, e não pela economia da usina.
