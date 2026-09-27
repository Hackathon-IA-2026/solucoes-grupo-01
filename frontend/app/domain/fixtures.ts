import type { Asset, AssetExposure, BatteryMode, BatteryScenario, ChartDataset, DataQuality, EvidenceMetadata, EvidenceState, EvidenceValue, Guidance, InterventionRequest, MaintenancePackage, MaintenanceWindow, Period } from "./types";

const historicalPeriod: Period = { start: "2025-07-01", end: "2026-06-30", label: "1 jul. 2025 a 30 jun. 2026" };
const scenarioPeriod: Period = { start: "2026-10-01", end: "2026-10-31", label: "Cenário de demonstração de outubro de 2026" };
const forecastPeriod: Period = { start: "2026-09-27", end: "2026-11-25", label: "27 set. a 25 nov. 2026" };
const modelPeriod: Period = { start: "2023-01-01", end: "2025-06-30", label: "Amostra histórica do experimento de seis horas" };

function evidence(value: number | null, unit: string, state: EvidenceState, method: string, source = "Portal de Dados Abertos do ONS", period = historicalPeriod, unavailableReason?: string, dataVersion = "snapshot-2026-08-31"): EvidenceValue {
  return { value, unit, period, source, dataVersion, method, state, unavailableReason };
}
function dataset(points: ChartDataset["points"], unit: string, state: EvidenceState, method: string, source = "Portal de Dados Abertos do ONS", period = historicalPeriod, dataVersion = "snapshot-2026-08-31"): ChartDataset {
  const metadata: EvidenceMetadata = { unit, period, source, dataVersion, method, state };
  return { points, evidence: metadata };
}
const simulated = (value: number | null, unit: string, method: string, reason?: string) => evidence(value, unit, "simulado", method, "API CurtailLess, fixture materializada da demonstração", scenarioPeriod, reason);
const calculatedScenario = (value: number | null, unit: string, method: string, reason?: string) => evidence(value, unit, "calculado", method, "API CurtailLess, fixture materializada da demonstração", scenarioPeriod, reason);
const informed = (value: number | null, unit: string, method: string) => evidence(value, unit, "informado pelo cliente", method, "Formulário da intervenção", scenarioPeriod);

export const assets: Asset[] = [
  { id: "asset-wind", name: "Ativo Eólico RN-01", technology: "Eólica", location: "Rio Grande do Norte", connectionPoint: "Ponto cadastral RN-500", anonymousEntities: 5, telemetry: "ausente" },
  { id: "asset-solar", name: "Ativo Solar MG-02", technology: "Solar", location: "Minas Gerais", connectionPoint: "Ponto cadastral MG-500", anonymousEntities: 3, telemetry: "simulada" },
];

const windExposure: AssetExposure = {
  summary: {
    total: evidence(844.8, "GWh", "calculado", "Soma da energia apurada em patamares de 30 minutos: val_geracaonaorealizadaapurada × 0,5 quando val_geracaolimitada não é nulo."),
    characterized: evidence(92, "%", "calculado", "Parcela da energia com razão caracterizada."),
    simultaneous: evidence(61, "%", "calculado", "Parcela histórica em eventos com duas ou mais entidades anonimizadas no ponto."),
    exclusive: evidence(39, "%", "calculado", "Complemento materializado da simultaneidade histórica."),
    entityCount: evidence(5, "entidades", "medido", "Contagem de associações cadastrais anonimizadas no ponto."),
  },
  history: dataset([
    { label: "jul/25", energetic: 27.8, reliability: 60.5, external: 3.1, unknown: 8.6 }, { label: "ago/25", energetic: 31.2, reliability: 58.4, external: 2.8, unknown: 7.6 },
    { label: "set/25", energetic: 30.1, reliability: 61.3, external: 2.1, unknown: 6.5 }, { label: "out/25", energetic: 24.6, reliability: 66.8, external: 2.9, unknown: 5.7 },
    { label: "nov/25", energetic: 29.4, reliability: 60.7, external: 2.3, unknown: 7.6 }, { label: "dez/25", energetic: 35.8, reliability: 52.1, external: 3.8, unknown: 8.3 },
    { label: "jan/26", energetic: 40.5, reliability: 45.4, external: 5.2, unknown: 8.9 }, { label: "fev/26", energetic: 44.6, reliability: 40.1, external: 5.9, unknown: 9.4 },
    { label: "mar/26", energetic: 39.7, reliability: 44.2, external: 6.4, unknown: 9.7 }, { label: "abr/26", energetic: 36.8, reliability: 47.3, external: 6.1, unknown: 9.8 },
    { label: "mai/26", energetic: 33.4, reliability: 51.6, external: 5.8, unknown: 9.2 }, { label: "jun/26", energetic: 34.1, reliability: 50.5, external: 5.2, unknown: 10.2 },
  ], "% da energia mensal", "calculado", "Participação mensal da energia apurada por razão registrada."),
  reasons: dataset([{ label: "Razão energética", value: 28 }, { label: "Confiabilidade", value: 61 }, { label: "Indisponibilidade externa", value: 3 }, { label: "Não caracterizada", value: 8 }], "% da energia", "calculado", "Distribuição histórica por razão publicada."),
  origins: dataset([{ label: "Sistêmica", value: 72 }, { label: "Local", value: 20 }, { label: "Não informada", value: 8 }], "% da energia", "calculado", "Distribuição histórica pela origem publicada, sem inferência a partir da razão."),
  seasonality: dataset([{ label: "seg.", value: 41 }, { label: "ter.", value: 46 }, { label: "qua.", value: 55 }, { label: "qui.", value: 52 }, { label: "sex.", value: 49 }, { label: "sáb.", value: 37 }, { label: "dom.", value: 34 }], "% de patamares", "calculado", "Frequência histórica por dia da semana."),
  hourly: dataset([{ label: "00h", value: 28 }, { label: "04h", value: 31 }, { label: "08h", value: 46 }, { label: "12h", value: 62 }, { label: "16h", value: 58 }, { label: "20h", value: 39 }], "% de patamares", "calculado", "Frequência histórica por hora BRT."),
  forecast60d: dataset([{ label: "28/9", value: 34 }, { label: "5/10", value: 47 }, { label: "12/10", value: 63 }, { label: "19/10", value: 56 }, { label: "26/10", value: 42 }, { label: "2/11", value: 58 }, { label: "9/11", value: 49 }, { label: "16/11", value: 37 }, { label: "23/11", value: 31 }], "% de chance de curtailment", "simulado", "Saída fictícia de um modelo de 60 dias, criada somente para demonstrar a experiência do produto; não usa o experimento de seis horas.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, "forecast-demo-2026-09-27"),
};

const solarExposure: AssetExposure = {
  summary: {
    total: evidence(126.4, "GWh", "simulado", "Soma sintética da energia não realizada em patamares de 30 minutos para o caso solar demonstrativo.", "API CurtailLess, fixture solar sintética"),
    characterized: evidence(87, "%", "simulado", "Parcela sintética da energia com razão caracterizada no cenário solar.", "API CurtailLess, fixture solar sintética"),
    simultaneous: evidence(43, "%", "simulado", "Parcela sintética em eventos com duas ou mais entidades anonimizadas.", "API CurtailLess, fixture solar sintética"),
    exclusive: evidence(57, "%", "simulado", "Parcela exclusiva materializada no caso solar sintético.", "API CurtailLess, fixture solar sintética"),
    entityCount: evidence(3, "entidades", "simulado", "Contagem sintética de associações cadastrais anonimizadas no ponto.", "API CurtailLess, fixture solar sintética"),
  },
  history: dataset([
    { label: "jul/25", energetic: 18, reliability: 69, external: 5, unknown: 8 }, { label: "ago/25", energetic: 20, reliability: 66, external: 5, unknown: 9 },
    { label: "set/25", energetic: 24, reliability: 62, external: 6, unknown: 8 }, { label: "out/25", energetic: 29, reliability: 57, external: 6, unknown: 8 },
    { label: "nov/25", energetic: 34, reliability: 51, external: 7, unknown: 8 }, { label: "dez/25", energetic: 39, reliability: 47, external: 6, unknown: 8 },
    { label: "jan/26", energetic: 42, reliability: 43, external: 7, unknown: 8 }, { label: "fev/26", energetic: 38, reliability: 48, external: 6, unknown: 8 },
    { label: "mar/26", energetic: 31, reliability: 54, external: 7, unknown: 8 }, { label: "abr/26", energetic: 27, reliability: 58, external: 7, unknown: 8 },
    { label: "mai/26", energetic: 22, reliability: 64, external: 6, unknown: 8 }, { label: "jun/26", energetic: 19, reliability: 67, external: 6, unknown: 8 },
  ], "% da energia mensal", "simulado", "Participação mensal sintética por razão, mantida separada da modalidade solar.", "API CurtailLess, fixture solar sintética"),
  reasons: dataset([{ label: "Razão energética", value: 29 }, { label: "Confiabilidade", value: 58 }, { label: "Indisponibilidade externa", value: 6 }, { label: "Não caracterizada", value: 7 }], "% da energia", "simulado", "Distribuição sintética por razão solar (_tm).", "API CurtailLess, fixture solar sintética"),
  origins: dataset([{ label: "Sistêmica", value: 64 }, { label: "Local", value: 28 }, { label: "Não informada", value: 8 }], "% da energia", "simulado", "Distribuição sintética pela origem solar, independente da razão.", "API CurtailLess, fixture solar sintética"),
  seasonality: dataset([{ label: "seg.", value: 28 }, { label: "ter.", value: 32 }, { label: "qua.", value: 39 }, { label: "qui.", value: 44 }, { label: "sex.", value: 36 }, { label: "sáb.", value: 27 }, { label: "dom.", value: 24 }], "% de patamares", "simulado", "Frequência sintética por dia da semana.", "API CurtailLess, fixture solar sintética"),
  hourly: dataset([{ label: "00h", value: 0 }, { label: "04h", value: 0 }, { label: "08h", value: 21 }, { label: "12h", value: 49 }, { label: "16h", value: 38 }, { label: "20h", value: 0 }], "% de patamares", "simulado", "Frequência sintética por hora BRT.", "API CurtailLess, fixture solar sintética"),
  forecast60d: dataset([{ label: "28/9", value: 24 }, { label: "5/10", value: 31 }, { label: "12/10", value: 42 }, { label: "19/10", value: 37 }, { label: "26/10", value: 28 }, { label: "2/11", value: 45 }, { label: "9/11", value: 39 }, { label: "16/11", value: 30 }, { label: "23/11", value: 26 }], "% de chance de curtailment", "simulado", "Saída fictícia de um modelo solar de 60 dias, criada somente para demonstrar a experiência do produto; não usa o experimento de seis horas.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, "forecast-demo-2026-09-27"),
  modality: dataset([{ label: "Constrained-off", value: 74 }, { label: "Curtailment parcial", value: 18 }, { label: "Modalidade não informada", value: 8 }], "% da energia", "simulado", "Modalidade solar sintética (_detail_tm), independente da razão e da origem.", "API CurtailLess, fixture solar sintética"),
};
export const assetExposureById: Record<string, AssetExposure> = { "asset-wind": windExposure, "asset-solar": solarExposure };
export const exposureSummary = windExposure.summary;
export const exposureSeries = windExposure.history;
export const reasonBreakdown = windExposure.reasons;
export const originBreakdown = windExposure.origins;
export const seasonality = windExposure.seasonality;
export const forecast60d = windExposure.forecast60d;

const windForecastWindows = [
  { label: "12 a 18 de outubro", likelihood: evidence(63, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Maior concentração simulada no horizonte." },
  { label: "2 a 8 de novembro", likelihood: evidence(58, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Segunda janela de maior atenção no cenário." },
  { label: "19 a 25 de outubro", likelihood: evidence(56, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Persistência simulada após o primeiro pico." },
];
const solarForecastWindows = [
  { label: "2 a 8 de novembro", likelihood: evidence(45, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão solar de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Maior concentração simulada no horizonte." },
  { label: "12 a 18 de outubro", likelihood: evidence(42, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão solar de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Segunda janela de maior atenção no cenário." },
  { label: "9 a 15 de novembro", likelihood: evidence(39, "%", "simulado", "Probabilidade fictícia para demonstrar uma previsão solar de 60 dias.", "API CurtailLess, fixture de previsão simulada", forecastPeriod, undefined, "forecast-demo-2026-09-27"), summary: "Nova elevação simulada no segundo mês." },
];
export const forecastWindowsByAsset = { "asset-wind": windForecastWindows, "asset-solar": solarForecastWindows };
export const forecastWindows = windForecastWindows;

const windDataQuality: DataQuality = {
  coverage: evidence(92, "%", "calculado", "Patamares válidos sobre patamares esperados."),
  delay: evidence(1, "dia", "medido", "Diferença entre publicação e materialização."),
  nullRate: evidence(2.4, "%", "calculado", "Campos nulos sobre registros recebidos."),
  duplicates: evidence(0, "registro", "calculado", "Duplicatas por chave natural do contrato."),
  granularity: "Patamares de 30 minutos, consolidados por mês nos gráficos históricos.",
  dataVersion: "snapshot-2026-08-31",
  schemaStatus: "Contrato público compatível; union_by_name habilitado na ingestão.",
  schemaChanges: "Nenhuma quebra detectada. Dois campos opcionais foram incorporados por nome.",
  lastMaterialization: "31 ago. 2026, 18:20 BRT",
  modelExecution: "Ranking demonstrativo materializado em 26 set. 2026. Modelo de seis horas permanece somente em pesquisa.",
};
const solarDataQuality: DataQuality = {
  coverage: evidence(100, "%", "simulado", "Registros sintéticos válidos sobre registros previstos na fixture solar.", "API CurtailLess, fixture solar sintética"),
  delay: evidence(0, "dia", "simulado", "Fixture solar carregada sem atraso de publicação externo.", "API CurtailLess, fixture solar sintética"),
  nullRate: evidence(1.8, "%", "simulado", "Campos nulos sobre registros sintéticos da fixture solar.", "API CurtailLess, fixture solar sintética"),
  duplicates: evidence(0, "registro", "simulado", "Duplicatas sintéticas por chave natural da fixture solar.", "API CurtailLess, fixture solar sintética"),
  granularity: "Patamares sintéticos de 30 minutos, consolidados por mês nos gráficos.",
  dataVersion: "solar-demo-snapshot-2026-09-26",
  schemaStatus: "Fixture solar sintética compatível com o contrato demonstrativo.",
  schemaChanges: "Não se aplica a uma fonte pública; fixture estática da demonstração.",
  lastMaterialization: "26 set. 2026, 15:00 BRT",
  modelExecution: "Ranking solar demonstrativo materializado. Nenhum modelo operacional foi executado.",
};
export const dataQualityByAsset: Record<string, DataQuality> = { "asset-wind": windDataQuality, "asset-solar": solarDataQuality };
export const dataQuality = windDataQuality;

export const exposureGuidance: Guidance = {
  data: "A análise combina o histórico da usina, padrões do ponto de conexão e uma previsão demonstrativa de 60 dias.",
  implication: "As janelas de maior chance simulada indicam onde a usina pode começar a comparar oportunidades de intervenção.",
  limitation: "A previsão de 60 dias ainda usa valores fictícios da demonstração e não sustenta uma decisão operacional real.",
  nextAction: "Informar a duração e as restrições da intervenção para comparar janelas elegíveis.", nextHref: "/manutencao",
};

function makeWindow(id: string, rank: number, start: string, end: string, eligible: boolean, reason: string, curtailment: number, loss: number, cost: number, energyDifference: number, moneyDifference: number, low: number, high: number, coverage: number, invalidators: string[], baseline = false): MaintenanceWindow {
  return {
    id, rank, start, end, eligible, eligibilityReason: reason, baseline,
    duration: informed(24, "horas", "Duração solicitada para a intervenção."),
    expectedCurtailment: simulated(curtailment, "MWh", "Curtailment esperado materializado pelo ranking prototípico."),
    interventionLoss: simulated(loss, "MWh", "Perda de oportunidade materializada durante a intervenção."),
    opportunityCost: simulated(cost, "R$", "Custo materializado para preço informado de R$ 300/MWh."),
    differenceFromBaseline: simulated(energyDifference, "MWh", "Diferença energética materializada contra a janela-base."),
    monetaryDifferenceFromBaseline: simulated(moneyDifference, "R$", "Diferença monetária materializada contra a janela-base."),
    uncertainty: { low: simulated(low, "MWh", "Limite inferior do intervalo materializado."), high: simulated(high, "MWh", "Limite superior do intervalo materializado.") },
    coverage: evidence(coverage, "%", "calculado", "Cobertura histórica das condições comparáveis.", "API CurtailLess, fixture materializada da demonstração", scenarioPeriod),
    invalidators,
  };
}

const windRequest: InterventionRequest = { duration: 24, notice: 7, start: "2026-10-01", end: "2026-10-31", unavailable: "11 e 12 de outubro", baseline: "2026-10-22T02:00", acceptableOutage: "até 24 horas, início entre 02h e 06h", operationalNotes: "Evitar troca de equipe no fim de semana.", price: 300 };
const solarRequest: InterventionRequest = { duration: 24, notice: 7, start: "2026-10-01", end: "2026-10-31", unavailable: "11 e 12 de outubro", baseline: "2026-10-20T02:00", acceptableOutage: "até 24 horas, início entre 02h e 06h", operationalNotes: "Preservar inspeção dos inversores na semana 3.", price: 300 };
const windWindows = [
  makeWindow("wind-alt-1", 1, "2026-10-06T02:00:00Z", "2026-10-07T02:00:00Z", true, "Atende duração, antecedência e indisponibilidades informadas.", 4.1, 18.4, 5520, -11.2, -3360, 14.2, 23.7, 88, ["Mudança de disponibilidade", "Condição fora da distribuição histórica"]),
  makeWindow("wind-alt-2", 2, "2026-10-16T02:00:00Z", "2026-10-17T02:00:00Z", true, "Atende duração e antecedência; coincide com uma reserva simulada parcial.", 6.7, 22.9, 6870, -6.7, -2010, 17.8, 29.4, 82, ["Reserva simulada", "Ausência de previsão meteorológica"]),
  makeWindow("wind-base", 3, "2026-10-22T02:00:00Z", "2026-10-23T02:00:00Z", true, "Janela-base informada pelo gestor.", 9.3, 29.6, 8880, 0, 0, 23.1, 37.8, 79, ["Baixa cobertura de telemetria", "Mudança cadastral"], true),
  makeWindow("wind-invalid", 4, "2026-10-11T02:00:00Z", "2026-10-12T02:00:00Z", false, "Dia marcado como indisponível pelo gestor.", 3.8, 17.9, 5370, -11.7, -3510, 13.5, 22.1, 86, ["Restrição informada pelo cliente"]),
];
const solarWindows = [
  makeWindow("solar-alt-1", 1, "2026-10-07T02:00:00Z", "2026-10-08T02:00:00Z", true, "Atende duração, antecedência e indisponibilidades informadas.", 2.8, 11.6, 3480, -7.5, -2250, 8.4, 15.3, 84, ["Série solar sintética", "Ausência de meteorologia ex ante"]),
  makeWindow("solar-alt-2", 2, "2026-10-15T02:00:00Z", "2026-10-16T02:00:00Z", true, "Atende duração e antecedência do cenário solar.", 3.4, 14.2, 4260, -4.9, -1470, 10.1, 19.8, 80, ["Série solar sintética", "Mudança de disponibilidade"]),
  makeWindow("solar-base", 3, "2026-10-20T02:00:00Z", "2026-10-21T02:00:00Z", true, "Janela-base informada pelo gestor.", 5.1, 19.1, 5730, 0, 0, 14.7, 25.6, 77, ["Telemetria simulada", "Mudança cadastral"], true),
  makeWindow("solar-invalid", 4, "2026-10-11T02:00:00Z", "2026-10-12T02:00:00Z", false, "Dia marcado como indisponível pelo gestor.", 2.3, 10.8, 3240, -8.3, -2490, 7.9, 14.4, 82, ["Restrição informada pelo cliente"]),
];
export const maintenancePackagesByAsset: Record<string, MaintenancePackage> = {
  "asset-wind": { id: "maintenance-wind-demo-01", assetId: "asset-wind", request: windRequest, windows: windWindows },
  "asset-solar": { id: "maintenance-solar-demo-01", assetId: "asset-solar", request: solarRequest, windows: solarWindows },
};
export const maintenanceWindows = windWindows;

const windReservations = [
  { id: "A", period: "15 a 16 de outubro", effect: "reduz elegibilidade da segunda janela eólica", state: "simulado" },
  { id: "B", period: "20 a 21 de outubro", effect: "sem conflito na configuração eólica", state: "simulado" },
];
const solarReservations = [
  { id: "C", period: "13 a 14 de outubro", effect: "reduz elegibilidade da primeira janela solar", state: "simulado" },
  { id: "D", period: "24 a 25 de outubro", effect: "sem conflito na configuração solar", state: "simulado" },
];
export const reservationsByAsset = { "asset-wind": windReservations, "asset-solar": solarReservations };
export const reservations = windReservations;
export const maintenanceGuidance: Guidance = {
  data: "O ranking compara alternativas elegíveis com a janela-base informada, usando resultados materializados para o ativo selecionado.",
  implication: "Uma diferença negativa indica menor perda no cenário, sem prometer o resultado futuro.",
  limitation: "O ranking é um protótipo baseado em histórico e sazonalidade; não possui meteorologia ex ante nem telemetria real.",
  nextAction: "Registrar uma escolha e avaliar a bateria sobre o curtailment residual associado à escolha.", nextHref: "/bateria",
};

function batteryPremises(mode: BatteryMode, power: number, capacity: number, efficiency: number, price: number, capex: number | null): Record<string, EvidenceValue> {
  const source = mode === "new" ? "Configuração candidata da demonstração" : "Cadastro simulado de bateria existente";
  return {
    power: evidence(power, "MW", "simulado", "Potência do cenário BESS materializado.", source, scenarioPeriod),
    capacity: evidence(capacity, "MWh", "simulado", "Capacidade do cenário BESS materializado.", source, scenarioPeriod),
    dischargeDuration: evidence(4, "horas", "simulado", "Duração explícita de descarga informada no cenário BESS.", source, scenarioPeriod),
    efficiency: evidence(efficiency, "%", "simulado", "Eficiência de ida e volta informada no cenário.", source, scenarioPeriod),
    price: evidence(price, "R$/MWh", "simulado", "Preço único parametrizado; não representa curva horária.", source, scenarioPeriod),
    availability: evidence(mode === "new" ? 96 : 91, "%", "simulado", "Disponibilidade do cenário materializado.", source, scenarioPeriod),
    degradation: evidence(mode === "new" ? 2 : null, "%/ano", "simulado", "Degradação anual do cenário.", source, scenarioPeriod, mode === "existing" ? "Degradação da bateria existente não validada" : undefined),
    cycles: evidence(mode === "new" ? 120 : 95, "ciclos/ano", "simulado", "Limite anual de ciclos no cenário materializado.", source, scenarioPeriod),
    connectionLimit: evidence(null, "MW", "simulado", "Limite operativo não materializado.", source, scenarioPeriod, "Limite operativo do ponto não fornecido"),
    ...(mode === "new" ? {
      capex: evidence(capex, "R$", "simulado", "CAPEX total informado para a configuração candidata.", source, scenarioPeriod),
      projectLife: evidence(10, "anos", "simulado", "Horizonte econômico informado para a triagem.", source, scenarioPeriod),
    } : {
      initialSoc: evidence(48, "%", "simulado", "Estado de carga inicial informado para a bateria existente.", source, scenarioPeriod),
      remainingLife: evidence(6, "anos", "simulado", "Vida útil remanescente informada para a bateria existente.", source, scenarioPeriod),
    }),
  };
}
function makeBattery(id: string, assetId: string, residualProfileId: string, mode: BatteryMode, residual: number, absorbable: number, cost: number, benefit: number, gap: number, power: number, capacity: number, efficiency: number, price: number, capex: number | null, sensitivity: ChartDataset["points"]): BatteryScenario {
  const premises = batteryPremises(mode, power, capacity, efficiency, price, capex);
  return {
    id, assetId, residualProfileId, mode, premises,
    request: {
      premises: Object.fromEntries(Object.entries(premises).map(([key, item]) => [key, item.value])),
      operationalRestrictions: mode === "new" ? "Operar apenas dentro dos limites cadastrados" : "Respeitar garantia, disponibilidade e limites cadastrados",
      meterBoundary: mode === "new" ? "Fronteira de medição a confirmar" : "Fronteira de medição cadastrada, ainda não validada",
      hourlyPriceSource: "Curva horária não fornecida; preço único parametrizado",
    },
    residualEnergy: simulated(residual, "MWh/ano", "Perfil residual materializado para o ativo e a janela de manutenção selecionados."),
    absorbableEnergy: calculatedScenario(absorbable, "MWh/ano", "Energia potencialmente absorvível já materializada para as premissas BESS."),
    annualizedCost: calculatedScenario(cost, "R$/ano", "CAPEX anualizado e custo operacional materializados."),
    parameterizedBenefit: calculatedScenario(benefit, "R$/ano", "Benefício materializado com preço único parametrizado; sem arbitragem horária."),
    economicGap: calculatedScenario(gap, "R$/ano", "Lacuna econômica materializada entre custo anualizado e benefício parametrizado."),
    sensitivity: dataset(sensitivity, "R$/ano", "simulado", "Sensibilidade materializada no backend; uma variável muda por vez.", "API CurtailLess, fixture materializada da demonstração", scenarioPeriod),
    missingInputs: ["Estado de carga cronológico", "Limite operativo do ponto", "Preço horário autorizado", "Degradação validada", "Fronteira de medição", "Restrições operacionais completas"],
  };
}
const sensitivityWindAlt = [{ label: "R$ 180", benefit: 38520, gap: 109480 }, { label: "R$ 300", benefit: 64200, gap: 83800 }, { label: "R$ 420", benefit: 89880, gap: 58120 }];
const sensitivityWindBase = [{ label: "R$ 180", benefit: 34200, gap: 113800 }, { label: "R$ 300", benefit: 57000, gap: 91000 }, { label: "R$ 420", benefit: 79800, gap: 68200 }];
const sensitivitySolarAlt = [{ label: "R$ 180", benefit: 19440, gap: 98560 }, { label: "R$ 300", benefit: 32400, gap: 85600 }, { label: "R$ 420", benefit: 45360, gap: 72640 }];
const sensitivitySolarBase = [{ label: "R$ 180", benefit: 17100, gap: 100900 }, { label: "R$ 300", benefit: 28500, gap: 89500 }, { label: "R$ 420", benefit: 39900, gap: 78100 }];
export const batteryScenarios: BatteryScenario[] = [
  makeBattery("bess-wind-alt-new", "asset-wind", "residual-wind-alt-1", "new", 628, 214, 148000, 64200, 83800, 25, 100, 88, 300, 1200000, sensitivityWindAlt),
  makeBattery("bess-wind-alt-existing", "asset-wind", "residual-wind-alt-1", "existing", 628, 176, 112000, 52800, 59200, 20, 80, 87, 300, null, sensitivityWindAlt),
  makeBattery("bess-wind-alt-2-new", "asset-wind", "residual-wind-alt-2", "new", 655, 202, 148000, 60600, 87400, 25, 100, 88, 300, 1200000, sensitivityWindBase),
  makeBattery("bess-wind-alt-2-existing", "asset-wind", "residual-wind-alt-2", "existing", 655, 169, 112000, 50700, 61300, 20, 80, 87, 300, null, sensitivityWindBase),
  makeBattery("bess-wind-base-new", "asset-wind", "residual-wind-base", "new", 702, 190, 148000, 57000, 91000, 25, 100, 88, 300, 1200000, sensitivityWindBase),
  makeBattery("bess-wind-base-existing", "asset-wind", "residual-wind-base", "existing", 702, 162, 112000, 48600, 63400, 20, 80, 87, 300, null, sensitivityWindBase),
  makeBattery("bess-solar-alt-new", "asset-solar", "residual-solar-alt-1", "new", 318, 108, 118000, 32400, 85600, 12, 48, 89, 300, 576000, sensitivitySolarAlt),
  makeBattery("bess-solar-alt-existing", "asset-solar", "residual-solar-alt-1", "existing", 318, 92, 94000, 27600, 66400, 10, 40, 86, 300, null, sensitivitySolarAlt),
  makeBattery("bess-solar-alt-2-new", "asset-solar", "residual-solar-alt-2", "new", 335, 102, 118000, 30600, 87400, 12, 48, 89, 300, 576000, sensitivitySolarBase),
  makeBattery("bess-solar-alt-2-existing", "asset-solar", "residual-solar-alt-2", "existing", 335, 87, 94000, 26100, 67900, 10, 40, 86, 300, null, sensitivitySolarBase),
  makeBattery("bess-solar-base-new", "asset-solar", "residual-solar-base", "new", 356, 95, 118000, 28500, 89500, 12, 48, 89, 300, 576000, sensitivitySolarBase),
  makeBattery("bess-solar-base-existing", "asset-solar", "residual-solar-base", "existing", 356, 82, 94000, 24600, 69400, 10, 40, 86, 300, null, sensitivitySolarBase),
];
export const batteryScenario = batteryScenarios[0];

export const batteryGuidance: Guidance = {
  data: "A triagem usa o perfil residual vinculado ao ativo e à decisão de manutenção registrados.",
  implication: "A lacuna econômica indica se a configuração merece estudo detalhado sob as premissas materializadas.",
  limitation: "Sem SOC cronológico, degradação, restrições operacionais, limite de conexão e preço horário, não existe despacho validado.",
  nextAction: "Reunir os dados técnicos ausentes ou registrar a triagem no relatório consolidado.", nextHref: "/relatorio",
};

export const modelResearch = {
  systemAuc: evidence(0.821, "AUC", "calculado", "AUC histórica do experimento de classificação de seis horas.", "Experimento CurtailLess", modelPeriod, undefined, "research-snapshot-2026-09"),
  setAuc: evidence(0.844, "AUC", "calculado", "AUC histórica por conjunto no experimento de seis horas.", "Experimento CurtailLess", modelPeriod, undefined, "research-snapshot-2026-09"),
  executionState: "Pesquisa reproduzida offline; sem endpoint operacional e sem execução automática na demonstração.",
  limitations: [
    "Os 30 conjuntos foram selecionados usando a série completa antes do split temporal.",
    "O vocabulário one-hot foi alinhado fora do conjunto de treino e precisa ser reajustado somente no treino.",
    "O modelo usa persistência e estado verificado da hora corrente; ainda não representa previsão operacional ex ante.",
  ],
};
