export type BatteryEstimate = {
  assetId: string;
  plantCapacityMw: number;
  batteryPowerMw: number;
  batteryEnergyMwh: number;
  dischargeHours: number;
  annualCycles: number;
  annualDeliveryMwh: number;
  roundTripEfficiencyPct: number;
  availabilityPct: number;
  capexMillionBrl: number;
  capacityRevenueMillionBrl: number;
  arbitrageRevenueMillionBrl: number;
  servicesRevenueMillionBrl: number;
  grossRevenueMillionBrl: number;
  annualOpexMillionBrl: number;
  netAnnualBenefitMillionBrl: number;
  simplePaybackYears: number;
  contributionAnalysis: string[];
  returnAnalysis: string[];
};

export const batteryEstimatesByAsset: Record<string, BatteryEstimate> = {
  RNEM13: {
    assetId: "RNEM13",
    plantCapacityMw: 67.2,
    batteryPowerMw: 20,
    batteryEnergyMwh: 40,
    dischargeHours: 2,
    annualCycles: 280,
    annualDeliveryMwh: 9462,
    roundTripEfficiencyPct: 88,
    availabilityPct: 96,
    capexMillionBrl: 70,
    capacityRevenueMillionBrl: 4.2,
    arbitrageRevenueMillionBrl: 2,
    servicesRevenueMillionBrl: 2.1,
    grossRevenueMillionBrl: 8.3,
    annualOpexMillionBrl: 1.05,
    netAnnualBenefitMillionBrl: 7.25,
    simplePaybackYears: 9.7,
    contributionAnalysis: [
      "Para Ventos de Santa Martina 13, a configuração inicial considera uma bateria de 20 MW e 40 MWh, equivalente a duas horas de descarga. A potência corresponde a cerca de 30% dos 67,2 MW cadastrados da usina.",
      "Com 280 ciclos anuais, eficiência de 88% e disponibilidade de 96%, o sistema entregaria aproximadamente 9.462 MWh por ano. A bateria pode deslocar parte da geração eólica para horários mais valorizados e responder com rapidez às necessidades do ponto de conexão.",
      "A coordenação usa a bateria como recurso operacional da usina e do conjunto conectado. O despacho pode combinar suavização de variações, atendimento a compromissos de potência e melhor uso da conexão ao longo do dia.",
    ],
    returnAnalysis: [
      "O investimento estimado de R$ 70 milhões gera R$ 8,30 milhões por ano em receitas combinadas. A composição considera R$ 4,20 milhões em produtos de capacidade e leilões, R$ 2 milhões em arbitragem e R$ 2,10 milhões em serviços e incentivos.",
      "Depois de R$ 1,05 milhão por ano de operação e manutenção, o benefício líquido estimado fica em R$ 7,25 milhões. A divisão do investimento por esse benefício resulta em retorno simples de 9,7 anos.",
      "O retorno não depende de eliminar curtailment. A bateria se paga pela combinação de disponibilidade em leilões, deslocamento de energia entre horários, serviços ao sistema e incentivos aplicáveis ao projeto.",
    ],
  },
  BAEA52: {
    assetId: "BAEA52",
    plantCapacityMw: 46.4,
    batteryPowerMw: 14,
    batteryEnergyMwh: 28,
    dischargeHours: 2,
    annualCycles: 280,
    annualDeliveryMwh: 6623,
    roundTripEfficiencyPct: 88,
    availabilityPct: 96,
    capexMillionBrl: 49,
    capacityRevenueMillionBrl: 2.94,
    arbitrageRevenueMillionBrl: 1.4,
    servicesRevenueMillionBrl: 1.47,
    grossRevenueMillionBrl: 5.81,
    annualOpexMillionBrl: 0.73,
    netAnnualBenefitMillionBrl: 5.08,
    simplePaybackYears: 9.7,
    contributionAnalysis: [
      "Para Assuruá 5 II, a estimativa utiliza uma bateria de 14 MW e 28 MWh, com duas horas de descarga. A potência representa aproximadamente 30% dos 46,4 MW cadastrados da usina.",
      "A configuração entrega cerca de 6.623 MWh por ano considerando 280 ciclos, eficiência de 88% e disponibilidade de 96%. O armazenamento permite guardar energia em períodos de menor valor e entregá-la quando a rede ou o mercado demandarem mais potência.",
      "O conjunto pode coordenar a bateria com a previsão eólica e com o limite do ponto BAGOR-230-A. Essa coordenação reduz oscilações na entrega e cria uma reserva rápida para compromissos operacionais.",
    ],
    returnAnalysis: [
      "O CAPEX estimado é de R$ 49 milhões. A receita anual chega a R$ 5,81 milhões, formada por R$ 2,94 milhões em capacidade e leilões, R$ 1,40 milhão em arbitragem e R$ 1,47 milhão em serviços e incentivos.",
      "Com R$ 730 mil de despesas anuais, o benefício líquido estimado é de R$ 5,08 milhões por ano. O retorno simples ocorre em aproximadamente 9,7 anos.",
      "A receita combina contratos de disponibilidade, diferenças de preço entre horários e serviços prestados ao sistema. O curtailment ajuda a definir o despacho, mas não é tratado como a única fonte de retorno financeiro.",
    ],
  },
  BAEB0B: {
    assetId: "BAEB0B",
    plantCapacityMw: 31.8,
    batteryPowerMw: 10,
    batteryEnergyMwh: 20,
    dischargeHours: 2,
    annualCycles: 280,
    annualDeliveryMwh: 4731,
    roundTripEfficiencyPct: 88,
    availabilityPct: 96,
    capexMillionBrl: 35,
    capacityRevenueMillionBrl: 2.1,
    arbitrageRevenueMillionBrl: 1,
    servicesRevenueMillionBrl: 1.05,
    grossRevenueMillionBrl: 4.15,
    annualOpexMillionBrl: 0.53,
    netAnnualBenefitMillionBrl: 3.62,
    simplePaybackYears: 9.7,
    contributionAnalysis: [
      "Para Serra da Babilônia B, a configuração proposta tem 10 MW de potência e 20 MWh de energia, suficientes para duas horas de descarga. A bateria equivale a cerca de 31% dos 31,8 MW da usina.",
      "Com 280 ciclos por ano, eficiência de 88% e disponibilidade de 96%, a entrega anual estimada é de 4.731 MWh. O porte menor acompanha a escala da usina sem exigir uma configuração desproporcional ao ativo.",
      "A bateria pode firmar parte da entrega eólica e reservar potência para momentos de maior necessidade do ponto BAMPD-230-A. O produto passa a coordenar previsão, estado de carga e compromissos operacionais em uma única programação.",
    ],
    returnAnalysis: [
      "O investimento estimado é de R$ 35 milhões, com receita anual combinada de R$ 4,15 milhões. A estimativa distribui R$ 2,10 milhões para capacidade e leilões, R$ 1 milhão para arbitragem e R$ 1,05 milhão para serviços e incentivos.",
      "Descontados R$ 530 mil anuais de operação e manutenção, o benefício líquido chega a R$ 3,62 milhões por ano. O prazo de retorno simples é de 9,7 anos.",
      "O modelo econômico combina fontes de receita para que a bateria não dependa de um único evento de rede. Contratos, arbitragem e serviços rápidos sustentam o retorno ao longo do horizonte do projeto.",
    ],
  },
  RNMVS2: {
    assetId: "RNMVS2",
    plantCapacityMw: 42.48,
    batteryPowerMw: 12,
    batteryEnergyMwh: 36,
    dischargeHours: 3,
    annualCycles: 300,
    annualDeliveryMwh: 9124,
    roundTripEfficiencyPct: 88,
    availabilityPct: 96,
    capexMillionBrl: 61.2,
    capacityRevenueMillionBrl: 3.67,
    arbitrageRevenueMillionBrl: 2.52,
    servicesRevenueMillionBrl: 1.84,
    grossRevenueMillionBrl: 8.03,
    annualOpexMillionBrl: 0.92,
    netAnnualBenefitMillionBrl: 7.11,
    simplePaybackYears: 8.6,
    contributionAnalysis: [
      "Para Monte Verde Solar II, a estimativa considera uma bateria de 12 MW e 36 MWh, com três horas de descarga. A potência corresponde a aproximadamente 28% dos 42,48 MW cadastrados da usina.",
      "Com 300 ciclos anuais, eficiência de 88% e disponibilidade de 96%, o sistema entregaria cerca de 9.124 MWh por ano. As três horas permitem transferir parte da produção solar para o fim da tarde e para o início da noite.",
      "A programação coordenada combina a curva solar, o estado de carga e o limite do ponto RNMTV-500-A. A bateria amplia a capacidade de firmar entrega após a queda da irradiância e de responder a solicitações do sistema.",
    ],
    returnAnalysis: [
      "O CAPEX estimado de R$ 61,20 milhões produz R$ 8,03 milhões em receitas anuais. A composição inclui R$ 3,67 milhões em capacidade e leilões, R$ 2,52 milhões em arbitragem e R$ 1,84 milhão em serviços e incentivos.",
      "Após R$ 920 mil em custos anuais, o benefício líquido fica em R$ 7,11 milhões por ano. O retorno simples estimado é de 8,6 anos.",
      "A arbitragem tem maior participação porque a geração solar pode ser deslocada para horas posteriores. Leilões, disponibilidade e serviços de rede completam a receita e reduzem a dependência de uma única aplicação.",
    ],
  },
  PBLZ3: {
    assetId: "PBLZ3",
    plantCapacityMw: 58.95,
    batteryPowerMw: 18,
    batteryEnergyMwh: 54,
    dischargeHours: 3,
    annualCycles: 300,
    annualDeliveryMwh: 13686,
    roundTripEfficiencyPct: 88,
    availabilityPct: 96,
    capexMillionBrl: 91.8,
    capacityRevenueMillionBrl: 5.51,
    arbitrageRevenueMillionBrl: 3.78,
    servicesRevenueMillionBrl: 2.75,
    grossRevenueMillionBrl: 12.04,
    annualOpexMillionBrl: 1.38,
    netAnnualBenefitMillionBrl: 10.66,
    simplePaybackYears: 8.6,
    contributionAnalysis: [
      "Para Luzia 3, a configuração estimada possui 18 MW e 54 MWh, com três horas de descarga. A potência equivale a aproximadamente 31% dos 58,95 MW cadastrados da usina.",
      "A bateria entregaria cerca de 13.686 MWh por ano com 300 ciclos, eficiência de 88% e disponibilidade de 96%. O porte permite deslocar uma parcela relevante da produção solar para horários posteriores ao pico de geração.",
      "A coordenação considera a previsão solar, o limite do ponto RNSTL-500-A e o estado de carga. O sistema pode reservar parte da capacidade para compromissos de potência e usar o restante em deslocamento horário e serviços de rede.",
    ],
    returnAnalysis: [
      "O investimento estimado é de R$ 91,80 milhões e a receita anual combinada chega a R$ 12,04 milhões. O total reúne R$ 5,51 milhões em capacidade e leilões, R$ 3,78 milhões em arbitragem e R$ 2,75 milhões em serviços e incentivos.",
      "Com despesas anuais estimadas em R$ 1,38 milhão, o benefício líquido é de R$ 10,66 milhões por ano. A recuperação simples do investimento ocorre em aproximadamente 8,6 anos.",
      "A escala de Luzia 3 permite distribuir a receita entre deslocamento da geração solar, disponibilidade contratada e serviços ao sistema. Essa combinação explica o retorno sem atribuir à bateria a eliminação do curtailment.",
    ],
  },
};
