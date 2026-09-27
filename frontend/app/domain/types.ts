export type EvidenceState = "medido" | "calculado" | "previsto" | "simulado" | "informado pelo cliente";

export type Period = { start: string; end: string; label: string };

export type EvidenceValue = {
  value: number | null;
  unit: string;
  period: Period;
  source: string;
  dataVersion: string;
  method: string;
  state: EvidenceState;
  unavailableReason?: string;
};

export type EvidenceMetadata = Omit<EvidenceValue, "value">;

export type DataQuality = {
  coverage: EvidenceValue;
  delay: EvidenceValue;
  nullRate: EvidenceValue;
  duplicates: EvidenceValue;
  granularity: string;
  dataVersion: string;
  schemaStatus: string;
  schemaChanges: string;
  lastMaterialization: string;
  modelExecution: string;
};

export type Asset = {
  id: string;
  name: string;
  technology: "Eólica" | "Solar";
  location: string;
  connectionPoint: string;
  anonymousEntities: number;
  telemetry: "ausente" | "simulada" | "fornecida";
};

export type ChartPoint = Record<string, string | number | null> & { label: string };
export type ChartDataset = { points: ChartPoint[]; evidence: EvidenceMetadata };

export type Guidance = {
  data: string;
  implication: string;
  limitation: string;
  nextAction: string;
  nextHref?: string;
};

export type InterventionRequest = {
  duration: number;
  notice: number;
  start: string;
  end: string;
  unavailable: string;
  baseline: string;
  acceptableOutage: string;
  operationalNotes: string;
  price: number | null;
};

export type MaintenanceWindow = {
  id: string;
  rank: number;
  start: string;
  end: string;
  duration: EvidenceValue;
  eligible: boolean;
  eligibilityReason: string;
  expectedCurtailment: EvidenceValue;
  interventionLoss: EvidenceValue;
  opportunityCost: EvidenceValue;
  differenceFromBaseline: EvidenceValue;
  monetaryDifferenceFromBaseline: EvidenceValue;
  uncertainty: { low: EvidenceValue; high: EvidenceValue };
  coverage: EvidenceValue;
  invalidators: string[];
  baseline?: boolean;
};

export type MaintenancePackage = {
  id: string;
  assetId: string;
  request: InterventionRequest;
  windows: MaintenanceWindow[];
};

export type DecisionRecord = {
  assetId: string;
  baselineId: string;
  selectedWindowId: string;
  justification: string;
  recordedAt: string;
  residualProfileId: string;
  energyDifference: EvidenceValue;
  monetaryDifference: EvidenceValue;
  premises: InterventionRequest;
};

export type BatteryMode = "new" | "existing";

export type BatterySelection = {
  assetId: string;
  scenarioId: string;
  residualProfileId: string;
  mode: BatteryMode;
  recordedAt: string;
};

export type BatteryScenarioRequest = {
  premises: Record<string, number | null>;
  operationalRestrictions: string;
  meterBoundary: string;
  hourlyPriceSource: string;
};

export type BatteryScenario = {
  id: string;
  assetId: string;
  residualProfileId: string;
  mode: BatteryMode;
  premises: Record<string, EvidenceValue>;
  request: BatteryScenarioRequest;
  residualEnergy: EvidenceValue;
  absorbableEnergy: EvidenceValue;
  annualizedCost: EvidenceValue;
  parameterizedBenefit: EvidenceValue;
  economicGap: EvidenceValue;
  sensitivity: ChartDataset;
  missingInputs: string[];
};

export type ForecastWindow = {
  label: string;
  likelihood: EvidenceValue;
  summary: string;
};

export type AssetExposure = {
  summary: { total: EvidenceValue; characterized: EvidenceValue; simultaneous: EvidenceValue; exclusive: EvidenceValue; entityCount: EvidenceValue };
  history: ChartDataset;
  reasons: ChartDataset;
  origins: ChartDataset;
  seasonality: ChartDataset;
  hourly: ChartDataset;
  forecast60d: ChartDataset;
  modality?: ChartDataset;
};

export type ExposureMetric = { value: number | null; unit: string };
export type ExposureDistribution = { label: string; value: number };

/**
 * Wire-only source and status labels accepted from the Exposição API.
 *
 * They are validated so an unexpected value cannot pass silently, but they are
 * deliberately absent from `ExposureAsset`, `ExposureView` and their children:
 * the screen must never render provenance, simulation labels or generation
 * modes.
 */
export type ExposureWireOrigin = "SIMULADO" | "OBSERVADO";
export type ExposureWireEntityStatus = "simulated" | "observed";

export type ExposureAsset = {
  assetId: string;
  name: string;
  entityLevel: "plant";
  technology: "wind" | "solar";
  state: string;
  connectionPoint: string;
  capacityMw: number | null;
  connectedAssetCount: number;
  operationalDataStatus: "simulated" | "client_connected";
  allocationCoverage: ExposureMetric | null;
  onsGroupId: string | null;
  onsGroupName: string | null;
  ceg: string | null;
};

export type ExposureForecastPoint = {
  forecastDate: string;
  displayLabel: string;
  expectedCurtailedMwh: number;
  lowerMwh: number;
  upperMwh: number;
  curtailmentProbability: number;
  potentialGenerationMwh: number;
  acceptedGenerationEnvelopeMwh: number;
  scheduledMaintenanceReliefMwh: number;
  avoidedCurtailmentMwh: number;
  riskReductionPercentagePoints: number;
};

export type ExposureForecastWindow = {
  start: string;
  end: string;
  expectedCurtailedMwh: number;
  meanProbability: number;
};

export type ExposureCriticalWindow = ExposureForecastWindow & {
  rank: number;
  startsAt: string;
  endsAt: string;
  intervalCount: number;
  windowHours: number;
  curtailmentProbability: number;
  scheduledMaintenanceReliefMwh: number;
  avoidedCurtailmentMwh: number;
  candidateMaintenanceReliefMwh: number | null;
};

export type ExposurePointEntity = {
  plantId: string;
  name: string;
  technology: "wind" | "solar";
  capacityMw: number;
  meanAvailableGenerationMw: number;
  meanCurtailedGenerationMw: number;
  restrictedDayShare: number;
  scheduledMaintenanceIntervals: number;
  scheduledMaintenanceDerate: number;
};

export type ExposurePointContext = {
  pointId: string;
  entityCount: number;
  installedCapacityMw: number;
  potentialGenerationMw: number;
  acceptedGenerationEnvelopeMw: number;
  estimatedExcessMw: number;
  scheduledMaintenanceReliefMw: number;
  envelopeInterceptMw: number;
  envelopeSlope: number;
  scheduledMaintenanceWindowCount: number;
  entities: ExposurePointEntity[];
};

export type ExposureSimulatedTelemetry = {
  generationMw: number;
  potentialGenerationMw: number;
  availabilityMw: number;
  operationalCapacityMw: number;
  acceptedGenerationLimitMw: number;
  potentiallyCurtailedMw: number;
  restricted: boolean;
  weatherValue: number;
  weatherUnit: string;
};

export type ExposureForecastProbabilityStatus =
  | "empirical_uncalibrated"
  | "backtested_calibrated"
  | "backtested_empirical_uncalibrated"
  | "baseline_historical_frequency"
  | "unavailable";

/**
 * Narrative shape currently served by the API.
 *
 * Task 5 replaces it with per-section objects (`paragraphs` + `generation_mode`).
 * Its schema lives in `exposure-api.ts` behind `exposureNarrativeSchema`, so that
 * change never touches plant, forecast or window validation.
 */
export type ExposureNarrative = Record<
  "secao-ativo" | "secao-resumo" | "secao-previsao" | "secao-razao-origem" | "secao-recorrencia" | "secao-qualidade",
  string[]
>;

export type ExposureView = {
  asset: ExposureAsset;
  lastDataUpdate: string;
  inputDigest: string;
  observedImpact: {
    totalCurtailedEnergy: ExposureMetric;
    eventDayShare: ExposureMetric;
    latestDailyCurtailedEnergy: ExposureMetric;
    trailing7DayMean: ExposureMetric;
    trailing30DayMean: ExposureMetric;
    characterizedShare: ExposureMetric;
    simultaneousShare: ExposureMetric;
    exclusiveShare: ExposureMetric;
    curtailedDayShare: ExposureMetric | null;
    allocationCoverage: ExposureMetric | null;
    periodStart: string;
    periodEnd: string;
  };
  forecast60d: {
    status: "demonstrative_simulation" | "unavailable";
    start: string | null;
    end: string | null;
    points: ExposureForecastPoint[];
    totalExpectedMwh: number | null;
    totalLowerMwh: number | null;
    totalUpperMwh: number | null;
    eventThresholdMwh: number | null;
    eventPercentile: number | null;
    probabilityStatus: ExposureForecastProbabilityStatus;
    topWindows: ExposureForecastWindow[];
    criticalWindows72h: ExposureCriticalWindow[];
  };
  associatedConditions: {
    reasons: ExposureDistribution[];
    origins: ExposureDistribution[];
    modalities: ExposureDistribution[];
  };
  recurrence: {
    timezone: "America/Sao_Paulo";
    weekdays: ExposureDistribution[];
    hours: ExposureDistribution[];
  };
  quality: {
    coverage: ExposureMetric;
    updateDelay: ExposureMetric;
    missingRate: ExposureMetric;
    duplicateCount: ExposureMetric;
  };
  pointContext: ExposurePointContext | null;
  simulatedTelemetry: ExposureSimulatedTelemetry | null;
  narrative: ExposureNarrative;
  limitations: string[];
};
