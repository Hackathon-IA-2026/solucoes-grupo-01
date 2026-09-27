import { afterEach, describe, expect, it, vi } from "vitest";
import { VERIFIED_EXPOSURE_PLANT_IDS, fetchExposureAssets, fetchExposureView } from "./exposure-api";

/**
 * Fixtures mirror the five verified individual plants of the demonstration
 * (ONS public registry links, generation group, CEG, connection point) and the
 * simulated entities attached to the same connection point.
 */
const plants = [
  {
    asset_id: "RNEM13",
    name: "Ventos de Santa Martina 13",
    entity_level: "plant",
    ons_group_id: "CJU_RNRDV",
    ons_group_name: "Rio do Vento",
    technology: "wind",
    state: "RN",
    capacity_mw: 67.2,
    ceg: "EOL.CV.RN.038322-8.01",
    connected_asset_count: 7,
    operational_data_status: "simulated",
    allocation_coverage: { value: 96.5, unit: "%" },
    connection_point: "RNCMM-500-A",
  },
  {
    asset_id: "BAEA52",
    name: "Assuruá 5 II",
    entity_level: "plant",
    ons_group_id: "CJU_BALRA",
    ons_group_name: "Laranjeiras",
    technology: "wind",
    state: "BA",
    capacity_mw: 46.4,
    ceg: "EOL.CV.BA.051785-2.01",
    connected_asset_count: 51,
    operational_data_status: "simulated",
    connection_point: "BAGOR-230-A",
  },
  {
    asset_id: "BAEB0B",
    name: "Serra da Babilônia B",
    entity_level: "plant",
    ons_group_id: "CJU_BASDB",
    ons_group_name: "Serra da Babilônia",
    technology: "wind",
    state: "BA",
    capacity_mw: 31.8,
    ceg: "EOL.CV.BA.040608-2.01",
    connected_asset_count: 9,
    operational_data_status: "simulated",
    connection_point: "BAMPD-230-A",
  },
  {
    asset_id: "RNMVS2",
    name: "Monte Verde Solar II",
    entity_level: "plant",
    ons_group_id: "CJU_RNMVS",
    ons_group_name: "Monte Verde Solar",
    technology: "solar",
    state: "RN",
    capacity_mw: 42.48,
    ceg: "UFV.RS.RN.045154-1.01",
    connected_asset_count: 4,
    operational_data_status: "simulated",
    connection_point: "RNMTV-500-A",
  },
  {
    asset_id: "PBLZ3",
    name: "Luzia 3",
    entity_level: "plant",
    ons_group_id: "CJU_PBLZA",
    ons_group_name: "Luzia",
    technology: "solar",
    state: "PB",
    capacity_mw: 58.95,
    ceg: "UFV.RS.PB.044470-7.01",
    connected_asset_count: 11,
    operational_data_status: "simulated",
    connection_point: "RNSTL-500-A",
  },
] as const;

const asset = plants[0];
const metric = (value: number | null, unit: string) => ({ value, unit });
const narrativeSections = ["secao-ativo", "secao-resumo", "secao-previsao", "secao-razao-origem", "secao-recorrencia", "secao-qualidade"] as const;
const narrative = Object.fromEntries(
  narrativeSections.map((key) => [key, { paragraphs: ["Interpretação validada."], generation_mode: "bedrock" }]),
);

const FIRST_FORECAST_DAY = Date.UTC(2026, 8, 26);
const DAY_MS = 86_400_000;

function isoDay(offset: number): string {
  return new Date(FIRST_FORECAST_DAY + offset * DAY_MS).toISOString().slice(0, 10);
}

function displayLabel(date: string): string {
  const [, month, day] = date.split("-");
  return `${day}/${month}`;
}

const points = Array.from({ length: 60 }, (_, index) => {
  const date = isoDay(index);
  return {
    forecast_date: date,
    display_label: displayLabel(date),
    expected_curtailed_mwh: 2 + index / 100,
    lower_mwh: 1,
    upper_mwh: 3 + index / 100,
    curtailment_probability: 0.25,
    potential_generation_mwh: 8.5,
    accepted_generation_envelope_mwh: 6.5,
    scheduled_maintenance_relief_mwh: 0.5,
    avoided_curtailment_mwh: 0.4,
    risk_reduction_percentage_points: 1.5,
  };
});

const criticalWindows = [
  {
    rank: 1,
    starts_at: "2026-10-12T00:00:00",
    ends_at: "2026-10-15T00:00:00",
    start: "2026-10-12",
    end: "2026-10-14",
    expected_curtailed_mwh: 130.5,
    mean_probability: 0.82,
    interval_count: 144,
    window_hours: 72,
    curtailment_probability: 1,
    scheduled_maintenance_relief_mwh: 4.2,
    avoided_curtailment_mwh: 12.1,
    candidate_maintenance_relief_mwh: 3.3,
  },
  {
    rank: 2,
    starts_at: "2026-10-15T00:00:00",
    ends_at: "2026-10-18T00:00:00",
    start: "2026-10-15",
    end: "2026-10-17",
    expected_curtailed_mwh: 118.2,
    mean_probability: 0.78,
    interval_count: 144,
    window_hours: 72,
    curtailment_probability: 1,
    scheduled_maintenance_relief_mwh: 1.1,
    avoided_curtailment_mwh: 9.8,
    candidate_maintenance_relief_mwh: 0,
  },
  {
    rank: 3,
    starts_at: "2026-10-05T00:00:00",
    ends_at: "2026-10-08T00:00:00",
    start: "2026-10-05",
    end: "2026-10-07",
    expected_curtailed_mwh: 96.4,
    mean_probability: 0.71,
    interval_count: 144,
    window_hours: 72,
    curtailment_probability: 0.98,
    scheduled_maintenance_relief_mwh: 0.7,
    avoided_curtailment_mwh: 7.5,
    candidate_maintenance_relief_mwh: 0,
  },
];

const pointContext = {
  point_id: "RNCMM-500-A",
  entity_count: 8,
  installed_capacity_mw: 504.8,
  potential_generation_mw: 210.4,
  accepted_generation_envelope_mw: 160.2,
  estimated_excess_mw: 50.2,
  scheduled_maintenance_relief_mw: 6.4,
  envelope: { intercept_mw: 120.5, slope: 0.3 },
  scheduled_maintenance_window_count: 12,
  simulated_entities: [
    {
      plant_id: "RNEM13",
      name: "Ventos de Santa Martina 13",
      technology: "wind",
      ons_group_id: "CJU_RNRDV",
      capacity_mw: 67.2,
      mean_available_generation_mw: 32.1,
      mean_curtailed_generation_mw: 12.4,
      restricted_day_share: 0.8,
      scheduled_maintenance_intervals: 240,
      scheduled_maintenance_derate: 0.35,
      operational_data_status: "simulated",
      origin: "SIMULADO",
    },
    {
      plant_id: "RNEM14",
      name: "Ventos de Santa Martina 14",
      technology: "wind",
      ons_group_id: "CJU_RNRDV",
      capacity_mw: 44.1,
      mean_available_generation_mw: 21.3,
      mean_curtailed_generation_mw: 8.2,
      restricted_day_share: 0.77,
      scheduled_maintenance_intervals: 180,
      scheduled_maintenance_derate: 0.42,
      operational_data_status: "simulated",
      origin: "SIMULADO",
    },
  ],
  origin: "SIMULADO",
};

const simulatedTelemetry = {
  generation_mw: 15.9,
  potential_generation_mw: 24.7,
  availability_mw: 45.2,
  operational_capacity_mw: 45.2,
  accepted_generation_limit_mw: 15.9,
  potentially_curtailed_mw: 8.8,
  restricted: true,
  weather_value: 8.6,
  weather_unit: "m/s",
  origin: "SIMULADO",
};

const view = {
  asset,
  last_data_update: "2026-09-25T00:00:00Z",
  input_digest: "a".repeat(64),
  observed_impact: {
    total_curtailed_energy: metric(100, "MWh"),
    event_day_share: metric(80, "%"),
    latest_daily_curtailed_energy: metric(12, "MWh/dia"),
    trailing_7_day_mean: metric(10, "MWh/dia"),
    trailing_30_day_mean: metric(8, "MWh/dia"),
    characterized_share: metric(90, "%"),
    simultaneous_share: metric(25, "%"),
    exclusive_share: metric(75, "%"),
    curtailed_day_share: metric(80, "%"),
    allocation_coverage: metric(96.5, "%"),
    period_start: "2024-04-01",
    period_end: "2026-09-25",
  },
  forecast_60d: {
    status: "demonstrative_simulation",
    start: points[0].forecast_date,
    end: points[59].forecast_date,
    points,
    total_expected_mwh: 130,
    total_lower_mwh: 60,
    total_upper_mwh: 200,
    event_threshold_mwh: 5.5,
    event_percentile: 0.75,
    probability_status: "baseline_historical_frequency",
    probability_source: "baseline_frequency_seasonal",
    simulation_method: "SIMULADO_FROM_ONS_HISTORY",
    window_definition: "daily curtailed-energy proxy at or above the asset historical 75th percentile",
    top_windows: [],
    critical_windows_72h: criticalWindows,
  },
  associated_conditions: { reasons: [{ label: "ENE", value: 60 }], origins: [], modalities: [] },
  recurrence: { timezone: "America/Sao_Paulo", weekdays: [], hours: [] },
  quality: {
    coverage: metric(98, "%"),
    update_delay: metric(2, "dias"),
    missing_rate: metric(1, "%"),
    duplicate_count: metric(0, "intervalos"),
  },
  narrative,
  limitations: ["Cenário demonstrativo."],
  point_context: pointContext,
  simulated_telemetry: simulatedTelemetry,
};

function respond(payload: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }),
    ),
  );
}

function forecastWith(patch: Record<string, unknown>) {
  return { ...view, forecast_60d: { ...view.forecast_60d, ...patch } };
}

afterEach(() => vi.unstubAllGlobals());

describe("cliente da API de Exposição", () => {
  it("lista exatamente as cinco usinas verificadas e mapeia grupo, CEG e ponto", async () => {
    respond({ items: plants });

    const result = await fetchExposureAssets();

    expect(result).toHaveLength(5);
    expect(result.map((item) => item.assetId)).toEqual([...VERIFIED_EXPOSURE_PLANT_IDS]);
    expect(result[0]).toMatchObject({
      assetId: "RNEM13",
      entityLevel: "plant",
      technology: "wind",
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      ceg: "EOL.CV.RN.038322-8.01",
      connectionPoint: "RNCMM-500-A",
    });
  });

  it("recusa catálogo com nível de conjunto gerador", async () => {
    respond({ items: [{ ...asset, entity_level: "generation_group" }, ...plants.slice(1)] });

    await expect(fetchExposureAssets()).rejects.toThrow();
  });

  it("recusa catálogo com identificador de conjunto CJU_", async () => {
    respond({ items: [{ ...asset, asset_id: "CJU_RNRDV" }, ...plants.slice(1)] });

    await expect(fetchExposureAssets()).rejects.toThrow();
  });

  it("recusa catálogo com identificador repetido", async () => {
    respond({ items: [asset, asset, ...plants.slice(1, 4)] });

    await expect(fetchExposureAssets()).rejects.toThrow();
  });

  it("recusa catálogo que não contém exatamente as cinco usinas", async () => {
    respond({ items: [...plants.slice(0, 4), { ...plants[4], asset_id: "RNEM99" }] });

    await expect(fetchExposureAssets()).rejects.toThrow();
  });

  it("valida e mapeia o pacote de 60 dias com janelas, ponto e telemetria", async () => {
    respond(view);

    const result = await fetchExposureView("RNEM13");

    expect(result.forecast60d.points).toHaveLength(60);
    expect(result.forecast60d.points[0]).toMatchObject({
      forecastDate: "2026-09-26",
      displayLabel: "26/09",
      potentialGenerationMwh: 8.5,
      acceptedGenerationEnvelopeMwh: 6.5,
      scheduledMaintenanceReliefMwh: 0.5,
      avoidedCurtailmentMwh: 0.4,
    });
    expect(result.forecast60d.criticalWindows72h).toHaveLength(3);
    expect(result.forecast60d.criticalWindows72h[0]).toMatchObject({
      rank: 1,
      intervalCount: 144,
      windowHours: 72,
      curtailmentProbability: 1,
    });
    expect(result.observedImpact.allocationCoverage).toEqual({ value: 96.5, unit: "%" });
    expect(result.asset.allocationCoverage).toEqual({ value: 96.5, unit: "%" });
    expect(result.asset.onsGroupName).toBe("Rio do Vento");
    expect(result.asset.ceg).toBe("EOL.CV.RN.038322-8.01");
    expect(result.pointContext?.entities).toHaveLength(2);
    expect(result.pointContext?.entities[0]).toMatchObject({
      plantId: "RNEM13",
      onsGroupId: "CJU_RNRDV",
    });
    expect(result.pointContext?.entities[1].onsGroupId).toBe("CJU_RNRDV");
    expect(result.pointContext?.envelopeSlope).toBe(0.3);
    expect(result.pointContext?.entities[0]).not.toHaveProperty("origin");
    expect(result.simulatedTelemetry?.acceptedGenerationLimitMw).toBe(15.9);
    expect(result.simulatedTelemetry?.potentiallyCurtailedMw).toBe(8.8);
    expect(result.simulatedTelemetry?.restricted).toBe(true);
    expect(result.narrative["secao-previsao"]).toEqual(["Interpretação validada."]);
  });

  it("não expõe procedência, rótulos de simulação nem modos de geração", async () => {
    respond(view);

    const result = await fetchExposureView("RNEM13");
    const serialized = JSON.stringify(result);

    expect(serialized).not.toContain("SIMULADO");
    expect(serialized).not.toContain("simulation_method");
    expect(serialized).not.toContain("generation_mode");
    expect(serialized).not.toContain("bedrock");
    expect(serialized).not.toContain("cached_bedrock");
    expect(serialized).not.toContain("deterministic_fallback");
    expect(result.simulatedTelemetry).not.toHaveProperty("origin");
    expect(result.pointContext).not.toHaveProperty("origin");
    expect(result.forecast60d).not.toHaveProperty("simulationMethod");
    expect(result.forecast60d).not.toHaveProperty("probabilitySource");
  });

  it("consome o objeto de seção e mantém somente os parágrafos validados", async () => {
    respond(view);

    const result = await fetchExposureView("RNEM13");

    expect(result.narrative["secao-ativo"]).toEqual(["Interpretação validada."]);
    expect(Object.keys(result.narrative)).toEqual([...narrativeSections]);
    for (const section of narrativeSections) {
      expect(result.narrative[section]).toBeInstanceOf(Array);
    }
    expect(JSON.stringify(result.narrative)).not.toContain("generation_mode");
  });

  it("aceita cache e fallback determinístico sem distinguir a seção na tela", async () => {
    respond({
      ...view,
      narrative: {
        ...narrative,
        "secao-resumo": { paragraphs: ["Resumo do cache."], generation_mode: "cached_bedrock" },
        "secao-qualidade": { paragraphs: ["Qualidade do fallback."], generation_mode: "deterministic_fallback" },
      },
    });

    const result = await fetchExposureView("RNEM13");

    expect(result.narrative["secao-resumo"]).toEqual(["Resumo do cache."]);
    expect(result.narrative["secao-qualidade"]).toEqual(["Qualidade do fallback."]);
  });

  it("recusa seção de narrativa sem o objeto esperado", async () => {
    respond({ ...view, narrative: { ...narrative, "secao-ativo": ["Interpretação sem seção."] } });

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa seção de narrativa sem geração declarada", async () => {
    respond({ ...view, narrative: { ...narrative, "secao-previsao": { paragraphs: ["Sem modo."] } } });

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa modo de geração desconhecido", async () => {
    respond({ ...view, narrative: { ...narrative, "secao-previsao": { paragraphs: ["Modo inválido."], generation_mode: "manual" } } });

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa seção de narrativa vazia", async () => {
    respond({ ...view, narrative: { ...narrative, "secao-recorrencia": { paragraphs: [], generation_mode: "bedrock" } } });

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa faixa estimada inconsistente", async () => {
    respond(forecastWith({ points: [{ ...points[0], lower_mwh: 4 }, ...points.slice(1)] }));

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa envelope aceito acima da geração potencial", async () => {
    respond(
      forecastWith({
        points: [{ ...points[0], accepted_generation_envelope_mwh: 9 }, ...points.slice(1)],
      }),
    );

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa rótulo diário fora do padrão DD/MM", async () => {
    respond(forecastWith({ points: [{ ...points[0], display_label: "26-09" }, ...points.slice(1)] }));

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa previsão com menos de 60 dias", async () => {
    respond(forecastWith({ points: points.slice(0, 59) }));

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa previsão com datas não consecutivas", async () => {
    respond(
      forecastWith({
        points: [points[0], { ...points[1], forecast_date: isoDay(3), display_label: displayLabel(isoDay(3)) }, ...points.slice(2)],
      }),
    );

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa previsão demonstrativa sem as três janelas de 72 horas", async () => {
    respond(forecastWith({ critical_windows_72h: criticalWindows.slice(0, 2) }));

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa janela que não cobre 144 intervalos de 72 horas", async () => {
    respond(
      forecastWith({
        critical_windows_72h: [{ ...criticalWindows[0], interval_count: 143 }, ...criticalWindows.slice(1)],
      }),
    );

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("recusa janelas de 72 horas sobrepostas", async () => {
    respond(
      forecastWith({
        critical_windows_72h: [
          criticalWindows[0],
          { ...criticalWindows[1], starts_at: "2026-10-14T00:00:00", start: "2026-10-14", end: "2026-10-16", ends_at: "2026-10-17T00:00:00" },
          criticalWindows[2],
        ],
      }),
    );

    await expect(fetchExposureView("RNEM13")).rejects.toThrow();
  });

  it("propaga falha HTTP sem usar fixtures", async () => {
    respond({ detail: "Ativo não encontrado" }, 404);

    await expect(fetchExposureView("RNEM99")).rejects.toThrow("HTTP 404");
  });
});
