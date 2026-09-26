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

export type AssetExposure = {
  summary: { total: EvidenceValue; characterized: EvidenceValue; simultaneous: EvidenceValue; exclusive: EvidenceValue; entityCount: EvidenceValue };
  history: ChartDataset;
  reasons: ChartDataset;
  origins: ChartDataset;
  seasonality: ChartDataset;
  hourly: ChartDataset;
  perspective: ChartDataset;
  modality?: ChartDataset;
};
