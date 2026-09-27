import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchExposureAssets, fetchExposureView } from "./exposure-api";

const asset = {
  asset_id: "CJU_RNRDV",
  name: "Conj. Rio do Vento",
  technology: "wind",
  state: "RN",
  connection_point: "RNCMM-500-A",
  capacity_mw: 504.8,
  connected_asset_count: 4,
  operational_data_status: "simulated",
};
const metric = (value: number | null, unit: string) => ({ value, unit });
const narrative = Object.fromEntries([
  "secao-ativo",
  "secao-resumo",
  "secao-previsao",
  "secao-razao-origem",
  "secao-recorrencia",
  "secao-qualidade",
].map((key) => [key, ["Interpretação validada."]]));
const points = Array.from({ length: 60 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 8, 26 + index)).toISOString().slice(0, 10);
  return {
    forecast_date: date,
    expected_curtailed_mwh: 2,
    lower_mwh: 1,
    upper_mwh: 3,
    curtailment_probability: 0.25,
  };
});
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
    period_start: "2024-04-01",
    period_end: "2026-09-25",
  },
  forecast_60d: {
    status: "demonstrative_simulation",
    start: points[0].forecast_date,
    end: points[59].forecast_date,
    points,
    total_expected_mwh: 120,
    total_lower_mwh: 60,
    total_upper_mwh: 180,
    top_windows: [],
  },
  associated_conditions: { reasons: [], origins: [], modalities: [] },
  recurrence: { timezone: "America/Sao_Paulo", weekdays: [], hours: [] },
  quality: {
    coverage: metric(98, "%"),
    update_delay: metric(2, "dias"),
    missing_rate: metric(1, "%"),
    duplicate_count: metric(0, "intervalos"),
  },
  narrative,
  limitations: ["Cenário demonstrativo."],
};

function respond(payload: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  })));
}

afterEach(() => vi.unstubAllGlobals());

describe("cliente da API de Exposição", () => {
  it("valida e mapeia o catálogo de ativos", async () => {
    respond({ items: [asset] });

    const result = await fetchExposureAssets();

    expect(result[0]).toMatchObject({ assetId: "CJU_RNRDV", technology: "wind" });
  });

  it("valida e mapeia o pacote consolidado de 60 dias", async () => {
    respond(view);

    const result = await fetchExposureView("CJU_RNRDV");

    expect(result.forecast60d.points).toHaveLength(60);
    expect(result.observedImpact.totalCurtailedEnergy.value).toBe(100);
    expect(result.narrative["secao-previsao"]).toEqual(["Interpretação validada."]);
  });

  it("recusa faixa estimada inconsistente", async () => {
    respond({
      ...view,
      forecast_60d: {
        ...view.forecast_60d,
        points: [{ ...points[0], lower_mwh: 4 }, ...points.slice(1)],
      },
    });

    await expect(fetchExposureView("CJU_RNRDV")).rejects.toThrow();
  });

  it("propaga falha HTTP sem usar fixtures", async () => {
    respond({ detail: "Ativo não encontrado" }, 404);

    await expect(fetchExposureView("CJU_UNKNOWN")).rejects.toThrow("HTTP 404");
  });
});
