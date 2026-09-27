import { cleanup, render, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExposureAsset, ExposureForecastPoint, ExposureView } from "~/domain/types";
import { useExposure } from "~/state/use-exposure";
import { ExposureScreen } from "./exposure-screen";

vi.mock("~/state/use-exposure", () => ({ useExposure: vi.fn() }));

/**
 * The topology canvas needs a measured layout, which jsdom does not provide. The
 * stub keeps the list view, which is the same content on narrow screens.
 */
vi.mock("@xyflow/react", () => ({
  ReactFlow: () => <div data-topology-canvas />,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom" },
}));

/** recharts needs a measured box; the stub only fixes the responsive size. */
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  const react = await vi.importActual<typeof import("react")>("react");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      react.cloneElement(children as ReactElement<Record<string, unknown>>, { width: 960, height: 320 }),
  };
});

afterEach(cleanup);

function plant(
  assetId: string,
  name: string,
  technology: "wind" | "solar",
  state: string,
  connectionPoint: string,
  capacityMw: number,
  onsGroupId: string,
  onsGroupName: string,
): ExposureAsset {
  return {
    assetId,
    name,
    entityLevel: "plant",
    technology,
    state,
    connectionPoint,
    capacityMw,
    connectedAssetCount: 2,
    operationalDataStatus: "simulated",
    allocationCoverage: { value: 96.5, unit: "%" },
    onsGroupId,
    onsGroupName,
    ceg: technology === "wind" ? "EOL.CV.RN.038322-8.01" : "UFV.RS.RN.045154-1.01",
  };
}

/**
 * The verified cohort holds one plant per context. `RNEM14` is added as the
 * same-group peer, so the reconciliation scope of the topology is exercised the
 * way the API returns it when a group has more than one plant.
 */
const assets: ExposureAsset[] = [
  plant("RNEM13", "Ventos de Santa Martina 13", "wind", "RN", "RNCMM-500-A", 67.2, "CJU_RNRDV", "Rio do Vento"),
  plant("RNEM14", "Ventos de Santa Martina 14", "wind", "RN", "RNCMM-500-A", 44.1, "CJU_RNRDV", "Rio do Vento"),
  plant("BAEA52", "Assuruá 5 II", "wind", "BA", "BAGOR-230-A", 46.4, "CJU_BALRA", "Laranjeiras"),
  plant("BAEB0B", "Serra da Babilônia B", "wind", "BA", "BAMPD-230-A", 31.8, "CJU_BASDB", "Serra da Babilônia"),
  plant("RNMVS2", "Monte Verde Solar II", "solar", "RN", "RNMTV-500-A", 42.48, "CJU_RNMVS", "Monte Verde Solar"),
  plant("PBLZ3", "Luzia 3", "solar", "PB", "RNSTL-500-A", 58.95, "CJU_PBLZA", "Luzia"),
];

const FIRST_DAY = Date.UTC(2026, 8, 26);
const DAY_MS = 86_400_000;

function isoDay(offset: number) {
  return new Date(FIRST_DAY + offset * DAY_MS).toISOString().slice(0, 10);
}

function displayLabel(date: string) {
  const [, month, day] = date.split("-");
  return `${day}/${month}`;
}

/** The band is 2,5 MWh wide inside the useful weather horizon and 6,5 after it. */
const forecastPoints: ExposureForecastPoint[] = Array.from({ length: 60 }, (_, index) => {
  const date = isoDay(index);
  const expected = 1 + index / 2;
  const bandWidth = index < 16 ? 2.5 : 6.5;
  return {
    forecastDate: date,
    displayLabel: displayLabel(date),
    expectedCurtailedMwh: expected,
    lowerMwh: expected - 0.25,
    upperMwh: expected - 0.25 + bandWidth,
    curtailmentProbability: 0.25,
    potentialGenerationMwh: 8.5,
    acceptedGenerationEnvelopeMwh: 6.5,
    scheduledMaintenanceReliefMwh: 0.5,
    avoidedCurtailmentMwh: 0.4,
    riskReductionPercentagePoints: 1.5,
  };
});

const narrativeParagraphs: Record<string, string[]> = {
  "secao-ativo": ["A usina selecionada é a entidade principal desta análise."],
  "secao-resumo": ["O histórico da própria usina concentra a estimativa."],
  "secao-previsao": ["O horizonte diário sustenta três períodos críticos."],
  "secao-razao-origem": ["As razões pertencem ao conjunto e não à usina."],
  "secao-recorrencia": ["A recorrência é diária e não horária."],
  "secao-qualidade": ["A faixa cresce depois do horizonte útil."],
};

const view: ExposureView = {
  asset: assets[0],
  lastDataUpdate: "2026-09-25T00:00:00Z",
  inputDigest: "a".repeat(64),
  observedImpact: {
    totalCurtailedEnergy: { value: 1234.5, unit: "MWh" },
    eventDayShare: { value: 80, unit: "%" },
    latestDailyCurtailedEnergy: { value: 12.3, unit: "MWh/dia" },
    trailing7DayMean: { value: 10.1, unit: "MWh/dia" },
    trailing30DayMean: { value: 8.2, unit: "MWh/dia" },
    characterizedShare: { value: 90, unit: "%" },
    simultaneousShare: { value: 25, unit: "%" },
    exclusiveShare: { value: 75, unit: "%" },
    curtailedDayShare: { value: 77.5, unit: "%" },
    allocationCoverage: { value: 96.5, unit: "%" },
    periodStart: "2024-04-01",
    periodEnd: "2026-09-25",
  },
  forecast60d: {
    status: "demonstrative_simulation",
    start: forecastPoints[0].forecastDate,
    end: forecastPoints[59].forecastDate,
    points: forecastPoints,
    totalExpectedMwh: 1000,
    totalLowerMwh: 30,
    totalUpperMwh: 1400,
    eventThresholdMwh: 5.5,
    eventPercentile: 0.75,
    probabilityStatus: "baseline_historical_frequency",
    topWindows: [],
    criticalWindows72h: [
      {
        rank: 1,
        startsAt: "2026-10-12T00:00:00",
        endsAt: "2026-10-15T00:00:00",
        start: "2026-10-12",
        end: "2026-10-14",
        expectedCurtailedMwh: 130.5,
        meanProbability: 0.82,
        intervalCount: 144,
        windowHours: 72,
        curtailmentProbability: 1,
        scheduledMaintenanceReliefMwh: 4.2,
        avoidedCurtailmentMwh: 12.1,
        candidateMaintenanceReliefMwh: 3.3,
      },
      {
        rank: 2,
        startsAt: "2026-10-15T00:00:00",
        endsAt: "2026-10-18T00:00:00",
        start: "2026-10-15",
        end: "2026-10-17",
        expectedCurtailedMwh: 118.2,
        meanProbability: 0.78,
        intervalCount: 144,
        windowHours: 72,
        curtailmentProbability: 0.98,
        scheduledMaintenanceReliefMwh: 1.1,
        avoidedCurtailmentMwh: 9.8,
        candidateMaintenanceReliefMwh: 0,
      },
      {
        rank: 3,
        startsAt: "2026-10-05T00:00:00",
        endsAt: "2026-10-08T00:00:00",
        start: "2026-10-05",
        end: "2026-10-07",
        expectedCurtailedMwh: 96.4,
        meanProbability: 0.71,
        intervalCount: 144,
        windowHours: 72,
        curtailmentProbability: 0.98,
        scheduledMaintenanceReliefMwh: 0.7,
        avoidedCurtailmentMwh: 7.5,
        candidateMaintenanceReliefMwh: 0,
      },
    ],
  },
  associatedConditions: {
    reasons: [{ label: "ENE", value: 60 }],
    origins: [],
    modalities: [],
  },
  recurrence: {
    timezone: "America/Sao_Paulo",
    weekdays: [
      { label: "seg", value: 20 },
      { label: "ter", value: 30 },
    ],
    hours: [],
  },
  quality: {
    coverage: { value: 98, unit: "%" },
    updateDelay: { value: 2, unit: "dias" },
    missingRate: { value: 1, unit: "%" },
    duplicateCount: { value: 0, unit: "intervalos" },
  },
  pointContext: {
    pointId: "RNCMM-500-A",
    entityCount: 2,
    installedCapacityMw: 111.3,
    potentialGenerationMw: 210.4,
    acceptedGenerationEnvelopeMw: 160.2,
    estimatedExcessMw: 50.2,
    scheduledMaintenanceReliefMw: 6.4,
    envelopeInterceptMw: 120.5,
    envelopeSlope: 0.3,
    scheduledMaintenanceWindowCount: 12,
    entities: [
      {
        plantId: "RNEM13",
        name: "Ventos de Santa Martina 13",
        technology: "wind",
        onsGroupId: "CJU_RNRDV",
        capacityMw: 67.2,
        meanAvailableGenerationMw: 32.1,
        meanCurtailedGenerationMw: 12.4,
        restrictedDayShare: 0.8,
        scheduledMaintenanceIntervals: 240,
        scheduledMaintenanceDerate: 0.35,
      },
      {
        plantId: "RNEM14",
        name: "Ventos de Santa Martina 14",
        technology: "wind",
        onsGroupId: "CJU_RNRDV",
        capacityMw: 44.1,
        meanAvailableGenerationMw: 21.3,
        meanCurtailedGenerationMw: 8.2,
        restrictedDayShare: 0.77,
        scheduledMaintenanceIntervals: 180,
        scheduledMaintenanceDerate: 0.42,
      },
    ],
  },
  simulatedTelemetry: {
    generationMw: 15.9,
    potentialGenerationMw: 24.7,
    availabilityMw: 45.2,
    operationalCapacityMw: 45.2,
    acceptedGenerationLimitMw: 15.9,
    potentiallyCurtailedMw: 8.8,
    restricted: true,
    weatherValue: 8.6,
    weatherUnit: "m/s",
  },
  narrative: {
    "secao-ativo": narrativeParagraphs["secao-ativo"],
    "secao-resumo": narrativeParagraphs["secao-resumo"],
    "secao-previsao": narrativeParagraphs["secao-previsao"],
    "secao-razao-origem": narrativeParagraphs["secao-razao-origem"],
    "secao-recorrencia": narrativeParagraphs["secao-recorrencia"],
    "secao-qualidade": narrativeParagraphs["secao-qualidade"],
  },
  limitations: ["Cenário demonstrativo."],
};

function renderScreen(override: ExposureView = view) {
  vi.mocked(useExposure).mockReturnValue({
    assets,
    selectedAssetId: override.asset.assetId,
    selectAsset: vi.fn(),
    view: override,
    loading: false,
    error: null,
    retry: vi.fn(),
  });
  return render(<ExposureScreen />);
}

function section(container: HTMLElement, id: string) {
  const element = container.querySelector(`#${id}`);
  if (!(element instanceof HTMLElement)) throw new Error(`Seção ${id} não encontrada`);
  return element;
}

beforeEach(() => vi.clearAllMocks());

describe("tela de Exposição por usina", () => {
  it("titula as seis colunas de interpretação com o mesmo texto", () => {
    const { container } = renderScreen();

    const titles = Array.from(container.querySelectorAll("[data-analysis-title]"));
    expect(titles).toHaveLength(6);
    for (const title of titles) expect(title.textContent).toBe("Análise dos dados");
    expect(container.querySelectorAll("[data-analysis-section]")).toHaveLength(6);
  });

  it("renderiza a narrativa validada de cada seção sem expor procedência nem modos", () => {
    const { container } = renderScreen();
    const text = container.textContent ?? "";

    expect(text).toContain("A análise considera somente a usina selecionada.");
    expect(text).toContain("A faixa cresce depois do horizonte útil.");
    for (const forbidden of [
      "ONS_PUBLICO",
      "PROXY_CALCULADO",
      "SIMULADO",
      "generation_mode",
      "bedrock",
      "deterministic_fallback",
      "materializado no backend",
      "Fonte:",
      "Método:",
      "Versão:",
      "CJU_",
    ]) {
      expect(text).not.toContain(forbidden);
    }
    expect(text).not.toMatch(/simulad/i);
    expect(text).not.toMatch(/calculad/i);
  });

  it("resume a usina e seus dados discretos na ilustração", () => {
    const { container } = renderScreen();
    const ativo = section(container, "secao-ativo");
    const ilustracao = within(ativo.querySelector("[data-plant-identity-illustration]") as HTMLElement);

    expect(ilustracao.getByText("Ventos de Santa Martina 13")).toBeInTheDocument();
    expect(ilustracao.getByText("Rio do Vento")).toBeInTheDocument();
    expect(ilustracao.getByText("RNCMM-500-A")).toBeInTheDocument();
    expect(ilustracao.getByText("RN")).toBeInTheDocument();
    expect(ilustracao.getByText("67,2 MW cadastrados")).toBeInTheDocument();
    expect(ilustracao.getByText("45,2 MW estimados")).toBeInTheDocument();
    expect(ativo.querySelector('[data-energy-illustration="wind"]')).not.toBeNull();
    expect(ativo.querySelector("[data-topology-list]")).toBeNull();
    expect(ativo.textContent).not.toContain("Eólica");
    expect(ativo.textContent).not.toContain("CEG");
    expect(ativo.textContent).not.toContain("CJU_");
  });

  it("resume o histórico da própria usina com médias, geração e capacidade", () => {
    const { container } = renderScreen();
    const resumo = within(section(container, "secao-resumo"));

    expect(resumo.getByText("1.234,5")).toBeInTheDocument();
    expect(resumo.getByText("77,5")).toBeInTheDocument();
    expect(resumo.getByText("10,1")).toBeInTheDocument();
    expect(resumo.getByText("8,2")).toBeInTheDocument();
    expect(resumo.getByText("15,9")).toBeInTheDocument();
    expect(resumo.getAllByText("45,2").length).toBeGreaterThan(0);
    // A energia do ponto nunca é apresentada como energia da usina.
    expect(resumo.queryByText("210,4")).toBeNull();
  });

  it("usa duas linhas, 60 dias e três janelas críticas resumidas", () => {
    const { container } = renderScreen();
    const previsao = section(container, "secao-previsao");

    expect(previsao.querySelector('[data-chart-lines="2"]')).not.toBeNull();
    expect(previsao.querySelector('[data-forecast-point-count="60"]')).not.toBeNull();
    expect(previsao.querySelector('[data-exposure-forecast="60d"]')).not.toBeNull();
    expect(previsao.querySelector("[data-critical-windows]")?.getAttribute("data-critical-windows")).toBe("3");

    const windows = Array.from(previsao.querySelectorAll("[data-critical-window]"));
    expect(windows).toHaveLength(3);
    for (const window of windows) expect(window.getAttribute("data-window-hours")).toBe("72");

    expect(previsao.textContent).toContain("12 a 14 de outubro");
    expect(previsao.textContent).toContain("Perda: 130,5 MWh");
    expect(previsao.textContent).not.toContain("144 intervalos de 30 min");
    expect(previsao.textContent).not.toContain("Limite inferior");
    expect(previsao.textContent).not.toContain("Limite superior");
  });

  it("remove a telemetria das outras usinas e mantém as estimativas", () => {
    const { container } = renderScreen();
    const razao = section(container, "secao-razao-origem");

    expect(razao.querySelectorAll("[data-point-entity]")).toHaveLength(0);
    expect(razao.textContent).not.toContain("Ventos de Santa Martina 14");
    expect(razao.textContent).not.toContain("21,3");

    const comparison = razao.querySelector("[data-maintenance-comparison]");
    expect(comparison).not.toBeNull();
    const scope = within(comparison as HTMLElement);
    expect(scope.getByText("210,4")).toBeInTheDocument();
    expect(scope.getByText("216,8")).toBeInTheDocument();
    expect(scope.getByText("6,4")).toBeInTheDocument();
  });

  it("descreve a recorrência sem relação meteorológica", () => {
    const { container } = renderScreen();
    const recorrencia = section(container, "secao-recorrencia");

    expect(recorrencia.textContent).toContain("Distribuição por dia da semana");
    expect(recorrencia.textContent).toContain("não permite calcular uma distribuição por horário");
    expect(recorrencia.querySelector("[data-weather-relationship]")).toBeNull();
    expect(recorrencia.textContent).not.toContain("Relação com a condição meteorológica");
  });

  it("mede cobertura, defasagem, ausências, duplicatas, alocação e a incerteza do horizonte", () => {
    const { container } = renderScreen();
    const qualidade = section(container, "secao-qualidade");
    const scope = within(qualidade);

    expect(scope.getByText("98")).toBeInTheDocument();
    expect(scope.getByText("1")).toBeInTheDocument();
    expect(scope.getByText("0")).toBeInTheDocument();
    expect(scope.getByText("96,5")).toBeInTheDocument();
    expect(qualidade.querySelector('[data-weather-horizon="16"]')).not.toBeNull();
    expect(qualidade.textContent).toContain("Amplitude média da faixa até o 16º dia");
    expect(qualidade.textContent).toContain("Amplitude média da faixa após o horizonte meteorológico útil");
    expect(scope.getByText("2,5")).toBeInTheDocument();
    expect(scope.getByText("6,5")).toBeInTheDocument();
  });
});
