import type { ExposureNarrativeSectionId } from "~/domain/types";

type ExposureCopy = Record<ExposureNarrativeSectionId, readonly string[]>;
type MaintenanceSectionId = "secao-janelas" | "secao-reducao" | "secao-ganho";
type MaintenanceCopy = Record<MaintenanceSectionId, readonly string[]>;

export const exposureAnalysisCopyByAsset: Record<string, ExposureCopy> = {
  RNEM13: {
    "secao-ativo": [
      "Ventos de Santa Martina 13 gera 28,5 MW diante de um potencial de 36,1 MW. A diferença de 7,6 MW aparece como energia potencialmente restringida, equivalente a 21% do potencial estimado neste momento.",
      "A capacidade operacional estimada é de 65,5 MW. A geração atual usa 43,5% dessa capacidade, enquanto o limite aceito no ponto mantém a entrega em 28,5 MW.",
    ],
    "secao-resumo": [
      "O histórico acumula 163.936,7 MWh de energia restringida e registra restrição em 80% dos dias analisados. Isso mostra que a limitação é recorrente para a usina, e não concentrada em poucos episódios.",
      "A média dos últimos 7 dias chegou a 450,9 MWh/dia, 24,2% acima da média de 363,0 MWh/dia dos últimos 30 dias. O período mais recente ficou mais severo que o padrão mensal.",
    ],
    "secao-previsao": [
      "A projeção soma 10.907,1 MWh de curtailment em 60 dias, média de 181,8 MWh/dia. As três janelas críticas concentram 34,7% desse total.",
      "O maior bloco ocorre de 7 a 9 de outubro, com 1.316,9 MWh. Os períodos de 15 a 17 e de 4 a 6 de outubro também merecem atenção por reunirem mais de 1.200 MWh cada.",
    ],
    "secao-razao-origem": [
      "No ponto de conexão, a geração potencial estimada é de 583,1 MW para um envelope aceito de 449,5 MW. O excesso chega a 115,7 MW, cerca de 19,8% do potencial do ponto.",
      "As 11 janelas de manutenção já agendadas retiram 11,1 MW da geração simultânea. Esse alívio corresponde a 1,9% do cenário sem manutenções e se associa a 16.024,1 MWh de curtailment evitado no horizonte.",
    ],
    "secao-recorrencia": [
      "Domingo concentra 21,8% da energia restringida do histórico e sábado responde por 15,9%. Juntos, os dois dias reúnem 37,6% do total semanal.",
      "A concentração no fim de semana ajuda a priorizar inspeções e intervenções que possam ser deslocadas para esses dias.",
    ],
    "secao-qualidade": [
      "O histórico e a alocação da usina têm cobertura de 100%, sem registros ausentes ou duplicados, e a atualização apresenta defasagem de 2 dias.",
      "A amplitude média da faixa passa de 69,2 MWh/dia nos primeiros 16 dias para 187,0 MWh/dia depois desse período, crescimento de 170,2%. O intervalo mais largo representa uma variedade maior de resultados possíveis no trecho distante.",
    ],
  },
  BAEA52: {
    "secao-ativo": [
      "Assuruá 5 II gera 20,3 MW diante de um potencial de 24,7 MW. A diferença de 4,4 MW aparece como energia potencialmente restringida, equivalente a 17,8% do potencial estimado.",
      "A capacidade operacional estimada é de 45,2 MW. A geração atual ocupa 45,0% dessa capacidade, com a entrega limitada ao mesmo patamar de 20,3 MW mostrado no painel.",
    ],
    "secao-resumo": [
      "O histórico acumula 94.987,3 MWh de energia restringida e registra restrição em 81,3% dos dias analisados. A frequência elevada indica exposição recorrente da usina.",
      "As médias de 7 e 30 dias estão praticamente iguais, em 88,9 e 89,2 MWh/dia. O nível recente permanece estável em relação ao mês.",
    ],
    "secao-previsao": [
      "A projeção soma 6.325,2 MWh de curtailment em 60 dias, média de 105,4 MWh/dia. As três janelas críticas concentram 30,1% desse total.",
      "O maior bloco ocorre de 12 a 14 de outubro, com 651,4 MWh, seguido por 15 a 17 de outubro, com 639,4 MWh, e 5 a 7 de outubro, com 612,9 MWh.",
    ],
    "secao-razao-origem": [
      "No ponto de conexão, a geração potencial estimada é de 901,6 MW para um envelope aceito de 723,8 MW. O excesso chega a 152,1 MW, cerca de 16,9% do potencial do ponto.",
      "As 36 janelas de manutenção já agendadas reduzem a geração simultânea em 8,9 MW. O horizonte mostra 12.774,4 MWh de curtailment evitado após considerar esse alívio.",
    ],
    "secao-recorrencia": [
      "Domingo concentra 18,1% da energia restringida do histórico e quinta-feira responde por 14,7%. Juntos, os dois dias reúnem 32,8% do total semanal.",
      "Esses picos indicam os dias em que a usina enfrenta maior repetição de cortes e orientam a escolha de períodos para atividades programadas.",
    ],
    "secao-qualidade": [
      "O histórico e a alocação da usina têm cobertura de 100%, sem registros ausentes ou duplicados, e a atualização apresenta defasagem de 2 dias.",
      "A amplitude média da faixa cresce de 63,7 para 121,1 MWh/dia após o 16º dia, aumento de 89,9%. A leitura do trecho distante deve considerar esse intervalo mais amplo de resultados.",
    ],
  },
  BAEB0B: {
    "secao-ativo": [
      "Serra da Babilônia B gera 14,0 MW diante de um potencial de 17,5 MW. A diferença de 3,5 MW aparece como energia potencialmente restringida, equivalente a 19,8% do potencial estimado.",
      "A capacidade operacional estimada é de 31,0 MW. A geração atual usa 45,2% dessa capacidade e acompanha o limite aceito de 14,0 MW apresentado no painel.",
    ],
    "secao-resumo": [
      "O histórico acumula 45.700,3 MWh de energia restringida e registra restrição em 80,2% dos dias analisados. A frequência mostra que os cortes fazem parte do padrão recorrente da usina.",
      "A média dos últimos 7 dias é de 54,8 MWh/dia, 16,4% acima da média de 47,1 MWh/dia dos últimos 30 dias. A exposição aumentou no período mais recente.",
    ],
    "secao-previsao": [
      "A projeção soma 3.382,1 MWh de curtailment em 60 dias, média de 56,4 MWh/dia. As três janelas críticas concentram 32,0% desse total.",
      "O maior bloco ocorre de 12 a 14 de outubro, com 373,1 MWh. As janelas de 4 a 6 e de 7 a 9 de outubro vêm logo depois, com 362,0 e 347,6 MWh.",
    ],
    "secao-razao-origem": [
      "No ponto de conexão, a geração potencial estimada é de 637,9 MW para um envelope aceito de 527,3 MW. O excesso chega a 89,9 MW, cerca de 14,1% do potencial do ponto.",
      "As 25 janelas de manutenção já agendadas reduzem a geração simultânea em 5,2 MW. Depois desse ajuste, o horizonte acumula 7.466,0 MWh de curtailment evitado.",
    ],
    "secao-recorrencia": [
      "Domingo concentra 21,9% da energia restringida do histórico e sábado responde por 18,3%. Juntos, os dois dias reúnem 40,2% do total semanal.",
      "A concentração no fim de semana cria uma referência direta para posicionar atividades que reduzam a geração justamente nos dias mais recorrentes.",
    ],
    "secao-qualidade": [
      "O histórico e a alocação da usina têm cobertura de 100%, sem registros ausentes ou duplicados, e a atualização apresenta defasagem de 2 dias.",
      "A amplitude média da faixa cresce de 22,7 para 51,8 MWh/dia após o 16º dia, aumento de 128,0%. O intervalo maior amplia a diferença entre os cenários inferior e superior no fim do horizonte.",
    ],
  },
  RNMVS2: {
    "secao-ativo": [
      "Monte Verde Solar II gera 9,3 MW diante de um potencial de 12,4 MW. A diferença de 3,1 MW aparece como energia potencialmente restringida, equivalente a 25,0% do potencial estimado.",
      "A capacidade operacional estimada é de 41,4 MW. A geração atual ocupa 22,5% dessa capacidade, enquanto o limite aceito mantém a entrega em 9,3 MW.",
    ],
    "secao-resumo": [
      "O histórico acumula 63.653,9 MWh de energia restringida e registra restrição em 63,2% dos dias analisados. Mais de seis em cada dez dias tiveram algum volume limitado.",
      "As médias de 7 e 30 dias são próximas, em 169,9 e 167,4 MWh/dia. O nível recente está 1,5% acima da média mensal e indica estabilidade.",
    ],
    "secao-previsao": [
      "A projeção soma 4.468,6 MWh de curtailment em 60 dias, média de 74,5 MWh/dia. As três janelas críticas concentram 21,0% desse total.",
      "O maior bloco ocorre de 26 a 28 de setembro, com 344,3 MWh. As janelas de 7 a 9 e de 14 a 16 de outubro somam aproximadamente 300 MWh cada.",
    ],
    "secao-razao-origem": [
      "No ponto de conexão, a geração potencial estimada é de 55,3 MW para um envelope aceito de 40,8 MW. O excesso chega a 13,6 MW, cerca de 24,6% do potencial do ponto.",
      "As 33 janelas de manutenção já agendadas retiram 0,2 MW da geração simultânea. O efeito acumulado no horizonte corresponde a 314,0 MWh de curtailment evitado.",
    ],
    "secao-recorrencia": [
      "Domingo concentra 20,9% da energia restringida do histórico e sábado responde por 15,3%. Juntos, os dois dias reúnem 36,2% do total semanal.",
      "A concentração no fim de semana ajuda a identificar períodos em que uma intervenção programada tende a coincidir com maior recorrência de cortes.",
    ],
    "secao-qualidade": [
      "O histórico e a alocação da usina têm cobertura de 100%, sem registros ausentes ou duplicados, e a atualização apresenta defasagem de 2 dias.",
      "A amplitude média da faixa cresce de 18,2 para 29,7 MWh/dia após o 16º dia, aumento de 62,8%. O intervalo mais amplo no trecho distante comporta uma variação maior de energia restringida.",
    ],
  },
  PBLZ3: {
    "secao-ativo": [
      "Luzia 3 gera 17,6 MW diante de um potencial de 21,2 MW. A diferença de 3,6 MW aparece como energia potencialmente restringida, equivalente a 17,1% do potencial estimado.",
      "A capacidade operacional estimada é de 57,5 MW. A geração atual ocupa 30,6% dessa capacidade e acompanha o limite aceito de 17,6 MW.",
    ],
    "secao-resumo": [
      "O histórico acumula 30.854,1 MWh de energia restringida e registra restrição em 57,0% dos dias analisados. A usina apresentou limitação em pouco mais da metade do período.",
      "A média dos últimos 7 dias é de 115,4 MWh/dia, 5,1% abaixo da média de 121,6 MWh/dia dos últimos 30 dias. O período recente mostra uma leve redução.",
    ],
    "secao-previsao": [
      "A projeção soma 4.463,4 MWh de curtailment em 60 dias, média de 74,4 MWh/dia. As três janelas críticas concentram 16,2% desse total.",
      "As janelas de 5 a 7, 19 a 21 e 12 a 14 de novembro têm volumes muito próximos, entre 240,2 e 241,1 MWh. A distribuição indica três blocos de atenção semelhantes ao longo do mês.",
    ],
    "secao-razao-origem": [
      "No ponto de conexão, a geração potencial estimada é de 141,7 MW para um envelope aceito de 118,4 MW. O excesso chega a 20,9 MW, cerca de 14,7% do potencial do ponto.",
      "As 47 janelas de manutenção já agendadas retiram 0,4 MW da geração simultânea. O efeito acumulado no horizonte corresponde a 537,5 MWh de curtailment evitado.",
    ],
    "secao-recorrencia": [
      "Domingo concentra 32,4% da energia restringida do histórico e sábado responde por 16,9%. Juntos, os dois dias reúnem 49,3% do total semanal.",
      "Quase metade do volume semanal aparece no fim de semana, o que torna esses dias uma referência direta para o planejamento de intervenções.",
    ],
    "secao-qualidade": [
      "O histórico e a alocação da usina têm cobertura de 100%, sem registros ausentes ou duplicados, e a atualização apresenta defasagem de 2 dias.",
      "A amplitude média da faixa passa de 8,5 para 9,8 MWh/dia após o 16º dia, aumento de 15,4%. A variação ao longo do horizonte permanece relativamente contida.",
    ],
  },
};

export const exposureAnalysisSupplementByAsset: Record<string, ExposureCopy> = {
  RNEM13: {
    "secao-ativo": ["A diferença entre 36,1 MW de potencial e 28,5 MW entregues mostra o volume que a usina poderia converter em geração efetiva se o limite do ponto aumentasse. Esse intervalo é a referência imediata para acompanhar mudanças na restrição."],
    "secao-resumo": ["A distância entre as médias de 7 e 30 dias indica aceleração recente. Se a média curta continuar acima da mensal, o impacto acumulado tende a crescer mais rapidamente nas próximas atualizações."],
    "secao-previsao": ["As janelas críticas reúnem mais de um terço do volume previsto em apenas nove dias. Elas são os períodos mais relevantes para comparar manutenção, disponibilidade e eventual deslocamento de produção."],
    "secao-razao-origem": ["O envelope aceita cerca de 77% da geração potencial do ponto. A diferença entre geração potencial, excesso e envelope ajuda a separar a pressão conjunta da rede do efeito individual da usina."],
    "secao-recorrencia": ["Os outros cinco dias distribuem os 62,4% restantes. A concentração de sábado e domingo é forte o suficiente para orientar o calendário, mas a exposição continua presente durante toda a semana."],
    "secao-qualidade": ["A cobertura completa permite comparar períodos sem corrigir lacunas na série. Para datas mais distantes, o intervalo entre os limites inferior e superior deve acompanhar o valor central da previsão."],
  },
  BAEA52: {
    "secao-ativo": ["Os 4,4 MW entre o potencial e a geração entregue representam a margem afetada pelo limite atual. Uma redução desse intervalo indicaria melhor aproveitamento da energia disponível pela usina."],
    "secao-resumo": ["A diferença de apenas 0,3% entre as médias curta e mensal mostra continuidade do padrão recente. Mudanças futuras ficam mais fáceis de identificar porque o ponto de partida está estável."],
    "secao-previsao": ["As três janelas críticas aparecem próximas em outubro e somam 1.903,7 MWh. Essa concentração permite tratar o período de 5 a 17 de outubro como o principal bloco de acompanhamento."],
    "secao-razao-origem": ["O envelope absorve aproximadamente 80% do potencial do ponto. As manutenções reduzem pouco menos de 1% da geração simultânea, mas o efeito se acumula ao longo das 36 janelas consideradas."],
    "secao-recorrencia": ["Os 67,2% restantes se distribuem pelos outros dias. Domingo e quinta-feira funcionam como referências para comparar se uma janela de manutenção coincide com os períodos mais recorrentes."],
    "secao-qualidade": ["Como a série está completa, a principal diferença entre o início e o fim do horizonte vem da abertura da faixa estimada. Depois do 16º dia, a distância média entre os limites quase dobra."],
  },
  BAEB0B: {
    "secao-ativo": ["A usina entrega cerca de quatro quintos do potencial estimado neste momento. Os 3,5 MW restantes formam a margem diretamente associada à restrição indicada no painel."],
    "secao-resumo": ["A média semanal supera a mensal em 7,7 MWh/dia. Essa diferença mostra que os últimos dias contribuíram com mais energia restringida do que o padrão observado ao longo do mês."],
    "secao-previsao": ["As três janelas críticas somam 1.082,8 MWh e ficam concentradas entre 4 e 14 de outubro. Esse intervalo reúne a parte mais densa da exposição prevista para a usina."],
    "secao-razao-origem": ["O envelope aceita aproximadamente 82,7% da geração potencial do ponto. A diferença restante ajuda a explicar por que ainda existe excesso mesmo depois de considerar as manutenções agendadas."],
    "secao-recorrencia": ["Sábado e domingo concentram dois quintos do volume semanal. Uma intervenção nesses dias tende a sobrepor mais horas de manutenção aos períodos historicamente mais afetados."],
    "secao-qualidade": ["A série completa sustenta a comparação direta entre as datas. No trecho distante, a faixa média fica 29,1 MWh/dia mais larga, por isso os limites passam a ter mais peso na leitura do valor esperado."],
  },
  RNMVS2: {
    "secao-ativo": ["A usina entrega três quartos do potencial estimado, enquanto um quarto permanece restringido. A diferença de 3,1 MW é a medida mais direta do impacto operacional mostrado nesta seção."],
    "secao-resumo": ["A proximidade entre as médias semanal e mensal indica um patamar persistente em torno de 168 MWh/dia. O histórico recente não apresenta uma mudança brusca de intensidade."],
    "secao-previsao": ["A primeira janela começa logo no início do horizonte e concentra 344,3 MWh. As duas janelas de outubro mantêm volumes semelhantes, formando uma sequência de três períodos prioritários."],
    "secao-razao-origem": ["O envelope aceita cerca de 73,8% do potencial do ponto. O excesso de 13,6 MW é expressivo em relação ao tamanho da rede associada à usina e explica a diferença exibida entre potencial e entrega."],
    "secao-recorrencia": ["Os demais dias respondem por 63,8% do volume semanal. O fim de semana concentra a maior parcela contínua e oferece uma referência simples para comparar datas de intervenção."],
    "secao-qualidade": ["A série completa permite acompanhar a abertura da faixa sem interferência de registros ausentes. Depois do 16º dia, a amplitude aumenta 11,5 MWh/dia em média."],
  },
  PBLZ3: {
    "secao-ativo": ["A geração entregue corresponde a aproximadamente 82,9% do potencial estimado. A margem de 3,6 MW mostra quanto da produção disponível permanece fora do limite aceito no momento."],
    "secao-resumo": ["A média semanal está 6,2 MWh/dia abaixo da mensal. A queda é moderada e indica redução recente do impacto sem apagar a recorrência observada em 57% dos dias."],
    "secao-previsao": ["As três janelas críticas têm praticamente o mesmo volume e aparecem em semanas diferentes de novembro. O planejamento pode comparar essas datas com pouca diferença de exposição entre elas."],
    "secao-razao-origem": ["O envelope aceita cerca de 83,5% da geração potencial do ponto. O excesso de 20,9 MW permanece como a principal diferença operacional, enquanto o alívio das manutenções é pequeno no instante analisado."],
    "secao-recorrencia": ["Domingo sozinho reúne quase um terço do volume semanal. A soma com sábado torna o fim de semana o bloco mais representativo para avaliar coincidência entre curtailment e manutenção."],
    "secao-qualidade": ["A faixa estimada cresce apenas 1,3 MWh/dia depois do 16º dia. Entre as cinco usinas, Luzia 3 apresenta a menor abertura relativa do intervalo ao longo do horizonte."],
  },
};

const scheduledReductionCopy = (plantName: string) => [
  `Antes de incluir ${plantName}, os quatro agendamentos existentes reduzem o curtailment previsto em 217,2 MWh no mês. O total passa de 4.529,8 para 4.312,6 MWh, queda de 4,8%.`,
  "As quedas do gráfico coincidem com 6 e 7, 15 e 16, 20 e 21, e 24 e 25 de outubro. Um novo agendamento acrescenta a redução da usina selecionada somente nos dias em que a intervenção estiver ativa.",
] as const;

export const maintenanceAnalysisCopyByAsset: Record<string, MaintenanceCopy> = {
  RNEM13: {
    "secao-janelas": [
      "Para Ventos de Santa Martina 13, a primeira opção começa em 6 de outubro e associa 4,1 MWh de perda evitada à intervenção de 24 horas. As alternativas de 16 e 22 de outubro mostram 6,7 e 9,3 MWh.",
      "A ordem também considera antecedência, duração e restrições operacionais. O botão Agendar abre a janela escolhida com data e horário preenchidos.",
    ],
    "secao-reducao": scheduledReductionCopy("Ventos de Santa Martina 13"),
    "secao-ganho": [
      "O cálculo de Ventos de Santa Martina 13 usa uma geração diária estimada de 38,4 MWh durante a intervenção. Depois da confirmação, o painel separa a redução atribuída à usina da redução que já vinha das outras manutenções.",
      "A perda média evitada distribui o benefício pelo número de dias da intervenção. A participação mostra quanto a usina acrescenta à redução geral do período.",
    ],
  },
  BAEA52: {
    "secao-janelas": [
      "Para Assuruá 5 II, a primeira opção começa em 6 de outubro e associa 4,1 MWh de perda evitada à intervenção de 24 horas. As alternativas de 16 e 22 de outubro mostram 6,7 e 9,3 MWh.",
      "A ordem também considera antecedência, duração e restrições operacionais. O botão Agendar abre a janela escolhida com data e horário preenchidos.",
    ],
    "secao-reducao": scheduledReductionCopy("Assuruá 5 II"),
    "secao-ganho": [
      "O cálculo de Assuruá 5 II usa uma geração diária estimada de 38,4 MWh durante a intervenção. Depois da confirmação, o painel separa a redução atribuída à usina da redução que já vinha das outras manutenções.",
      "A perda média evitada distribui o benefício pelo número de dias da intervenção. A participação mostra quanto a usina acrescenta à redução geral do período.",
    ],
  },
  BAEB0B: {
    "secao-janelas": [
      "Para Serra da Babilônia B, a primeira opção começa em 6 de outubro e associa 4,1 MWh de perda evitada à intervenção de 24 horas. As alternativas de 16 e 22 de outubro mostram 6,7 e 9,3 MWh.",
      "A ordem também considera antecedência, duração e restrições operacionais. O botão Agendar abre a janela escolhida com data e horário preenchidos.",
    ],
    "secao-reducao": scheduledReductionCopy("Serra da Babilônia B"),
    "secao-ganho": [
      "O cálculo de Serra da Babilônia B usa uma geração diária estimada de 38,4 MWh durante a intervenção. Depois da confirmação, o painel separa a redução atribuída à usina da redução que já vinha das outras manutenções.",
      "A perda média evitada distribui o benefício pelo número de dias da intervenção. A participação mostra quanto a usina acrescenta à redução geral do período.",
    ],
  },
  RNMVS2: {
    "secao-janelas": [
      "Para Monte Verde Solar II, a primeira opção começa em 7 de outubro e associa 2,8 MWh de perda evitada à intervenção de 24 horas. As alternativas de 15 e 20 de outubro mostram 3,4 e 5,1 MWh.",
      "A ordem também considera antecedência, duração e restrições operacionais. O botão Agendar abre a janela escolhida com data e horário preenchidos.",
    ],
    "secao-reducao": scheduledReductionCopy("Monte Verde Solar II"),
    "secao-ganho": [
      "O cálculo de Monte Verde Solar II usa uma geração diária estimada de 31,6 MWh durante a intervenção. Depois da confirmação, o painel separa a redução atribuída à usina da redução que já vinha das outras manutenções.",
      "A perda média evitada distribui o benefício pelo número de dias da intervenção. A participação mostra quanto a usina acrescenta à redução geral do período.",
    ],
  },
  PBLZ3: {
    "secao-janelas": [
      "Para Luzia 3, a primeira opção começa em 7 de outubro e associa 2,8 MWh de perda evitada à intervenção de 24 horas. As alternativas de 15 e 20 de outubro mostram 3,4 e 5,1 MWh.",
      "A ordem também considera antecedência, duração e restrições operacionais. O botão Agendar abre a janela escolhida com data e horário preenchidos.",
    ],
    "secao-reducao": scheduledReductionCopy("Luzia 3"),
    "secao-ganho": [
      "O cálculo de Luzia 3 usa uma geração diária estimada de 31,6 MWh durante a intervenção. Depois da confirmação, o painel separa a redução atribuída à usina da redução que já vinha das outras manutenções.",
      "A perda média evitada distribui o benefício pelo número de dias da intervenção. A participação mostra quanto a usina acrescenta à redução geral do período.",
    ],
  },
};

export const maintenanceAnalysisSupplementByAsset: Record<string, MaintenanceCopy> = {
  RNEM13: {
    "secao-janelas": ["Para Ventos de Santa Martina 13, escolher uma janela sugerida também reduz o trabalho de configuração: data, horário e duração entram preenchidos no formulário. As observações continuam abertas para registrar as condições específicas da intervenção."],
    "secao-reducao": ["No gráfico, a distância entre o curtailment inicial e o residual representa a redução programada. Os dias sem manutenção mantêm as duas referências próximas; as diferenças aparecem nas datas dos quatro agendamentos."],
    "secao-ganho": ["Depois do agendamento, compare os 38,4 MWh/dia da usina com o curtailment residual da janela. Quanto maior a sobreposição entre esses volumes, maior é a parcela da intervenção realizada durante uma limitação que já ocorreria."],
  },
  BAEA52: {
    "secao-janelas": ["Para Assuruá 5 II, as três opções cobrem datas distintas do mês e mantêm a mesma duração de 24 horas. A escolha pode considerar a perda evitada junto com a disponibilidade de equipe e os serviços previstos."],
    "secao-reducao": ["A redução de 217,2 MWh corresponde à soma dos quatro agendamentos já listados. Quando Assuruá 5 II for incluída, o gráfico acrescentará sua contribuição ao dia correspondente e recalculará o volume residual."],
    "secao-ganho": ["A referência de 38,4 MWh/dia limita a redução atribuída à usina em cada dia. O painel evita contar como benefício uma quantidade maior que o curtailment ainda restante depois das outras manutenções."],
  },
  BAEB0B: {
    "secao-janelas": ["Para Serra da Babilônia B, o ranking organiza as datas antes da abertura do formulário. A primeira opção prioriza a aderência aos parâmetros informados, enquanto as seguintes oferecem alternativas dentro do mesmo mês."],
    "secao-reducao": ["O valor residual de 4.312,6 MWh é o que permanece depois de descontar os agendamentos existentes. A diferença diária mostra onde uma nova manutenção pode ampliar a redução sem ultrapassar o curtailment previsto."],
    "secao-ganho": ["A contribuição de Serra da Babilônia B será limitada a 38,4 MWh por dia completo de intervenção e ao volume residual disponível. Essa regra mantém o ganho individual compatível com o panorama geral."],
  },
  RNMVS2: {
    "secao-janelas": ["Para Monte Verde Solar II, as opções de 7, 15 e 20 de outubro distribuem a intervenção por três semanas. A comparação entre 2,8, 3,4 e 5,1 MWh mostra a perda evitada associada a cada escolha."],
    "secao-reducao": ["Os quatro agendamentos existentes retiram 217,2 MWh de um total mensal de 4.529,8 MWh. A manutenção de Monte Verde Solar II passa a aparecer como uma camada adicional somente depois da confirmação."],
    "secao-ganho": ["A referência de 31,6 MWh/dia representa a geração solar retirada durante uma intervenção completa. O resultado individual será o menor valor entre essa geração e o curtailment residual existente na mesma data."],
  },
  PBLZ3: {
    "secao-janelas": ["Para Luzia 3, as opções de 7, 15 e 20 de outubro permitem comparar três semanas com a mesma duração. O aumento de 2,8 para 5,1 MWh entre a primeira e a terceira mostra como a coincidência com o curtailment muda entre as datas."],
    "secao-reducao": ["A queda mensal de 4,8% vem apenas das manutenções já confirmadas no panorama. Ao agendar Luzia 3, o gráfico descontará também a parcela da usina durante as horas efetivamente sobrepostas ao período previsto."],
    "secao-ganho": ["Para Luzia 3, o cálculo usa até 31,6 MWh por dia completo. A comparação entre redução individual, redução geral e curtailment residual mostra quanto do efeito vem da usina e quanto já existia no calendário."],
  },
};
