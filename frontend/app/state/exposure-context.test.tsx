import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchExposureAssets, fetchExposureView } from "~/domain/exposure-api";
import type { ExposureAsset, ExposureView } from "~/domain/types";
import { ExposureProvider } from "~/state/exposure-context";
import { useExposure } from "~/state/use-exposure";

vi.mock("~/domain/exposure-api", () => ({
  fetchExposureAssets: vi.fn(),
  fetchExposureView: vi.fn(),
}));

const wind: ExposureAsset = {
  assetId: "RNEM13",
  name: "Ventos de Santa Martina 13",
  entityLevel: "plant",
  technology: "wind",
  state: "RN",
  connectionPoint: "RNCMM-500-A",
  capacityMw: 67.2,
  connectedAssetCount: 7,
  operationalDataStatus: "simulated",
  allocationCoverage: { value: 96.5, unit: "%" },
  onsGroupId: "CJU_RNRDV",
  onsGroupName: "Rio do Vento",
  ceg: "EOL.CV.RN.038322-8.01",
};
const solar: ExposureAsset = {
  assetId: "RNMVS2",
  name: "Monte Verde Solar II",
  entityLevel: "plant",
  technology: "solar",
  state: "RN",
  connectionPoint: "RNMTV-500-A",
  capacityMw: 42.48,
  connectedAssetCount: 4,
  operationalDataStatus: "simulated",
  allocationCoverage: { value: 91.2, unit: "%" },
  onsGroupId: "CJU_RNMVS",
  onsGroupName: "Monte Verde Solar",
  ceg: "UFV.RS.RN.045154-1.01",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function exposureView(asset: ExposureAsset): ExposureView {
  const unavailable = { value: null, unit: "%" };
  return {
    asset,
    lastDataUpdate: "2026-09-25T00:00:00Z",
    inputDigest: "a".repeat(64),
    observedImpact: {
      totalCurtailedEnergy: { value: null, unit: "MWh" },
      eventDayShare: unavailable,
      latestDailyCurtailedEnergy: { value: null, unit: "MWh/dia" },
      trailing7DayMean: { value: null, unit: "MWh/dia" },
      trailing30DayMean: { value: null, unit: "MWh/dia" },
      characterizedShare: unavailable,
      simultaneousShare: unavailable,
      exclusiveShare: unavailable,
      curtailedDayShare: null,
      allocationCoverage: null,
      periodStart: "2024-04-01",
      periodEnd: "2026-09-25",
    },
    forecast60d: {
      status: "unavailable",
      start: null,
      end: null,
      points: [],
      totalExpectedMwh: null,
      totalLowerMwh: null,
      totalUpperMwh: null,
      eventThresholdMwh: null,
      eventPercentile: null,
      probabilityStatus: "unavailable",
      topWindows: [],
      criticalWindows72h: [],
    },
    associatedConditions: { reasons: [], origins: [], modalities: [] },
    recurrence: { timezone: "America/Sao_Paulo", weekdays: [], hours: [] },
    quality: {
      coverage: unavailable,
      updateDelay: { value: null, unit: "dias" },
      missingRate: unavailable,
      duplicateCount: { value: null, unit: "intervalos" },
    },
    pointContext: null,
    simulatedTelemetry: null,
    narrative: {
      "secao-ativo": ["Ativo."],
      "secao-resumo": ["Resumo."],
      "secao-previsao": ["Previsão."],
      "secao-razao-origem": ["Condições."],
      "secao-recorrencia": ["Recorrência."],
      "secao-qualidade": ["Qualidade."],
    },
    limitations: [],
  };
}

beforeEach(() => vi.clearAllMocks());

describe("ExposureProvider", () => {
  it("cancela a resposta anterior ao trocar de usina", async () => {
    const first = deferred<ExposureView>();
    vi.mocked(fetchExposureAssets).mockResolvedValue([wind, solar]);
    vi.mocked(fetchExposureView)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(exposureView(solar));
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(fetchExposureView).toHaveBeenCalledWith("RNEM13", expect.any(AbortSignal)));
    const firstSignal = vi.mocked(fetchExposureView).mock.calls[0][1];
    act(() => result.current.selectAsset("RNMVS2"));

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("RNMVS2"));
    expect(firstSignal?.aborted).toBe(true);
    first.resolve(exposureView(wind));
    await Promise.resolve();
    expect(result.current.view?.asset.assetId).toBe("RNMVS2");
  });

  it("repete o catálogo após uma falha completa", async () => {
    vi.mocked(fetchExposureAssets)
      .mockRejectedValueOnce(new Error("falha de rede"))
      .mockResolvedValueOnce([wind]);
    vi.mocked(fetchExposureView).mockResolvedValue(exposureView(wind));
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(result.current.error).toBe("falha de rede"));
    act(() => result.current.retry());

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("RNEM13"));
    expect(fetchExposureAssets).toHaveBeenCalledTimes(2);
  });

  it("seleciona somente a usina informada e ignora identificadores desconhecidos", async () => {
    vi.mocked(fetchExposureAssets).mockResolvedValue([wind, solar]);
    vi.mocked(fetchExposureView).mockImplementation((assetId: string) =>
      Promise.resolve(exposureView(assetId === solar.assetId ? solar : wind)),
    );
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("RNEM13"));
    act(() => result.current.selectAsset("CJU_RNRDV"));
    expect(result.current.selectedAssetId).toBe("RNEM13");
    act(() => result.current.selectAsset("RNMVS2"));

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("RNMVS2"));
    expect(fetchExposureView).toHaveBeenCalledWith("RNMVS2", expect.any(AbortSignal));
    expect(result.current.view?.asset.onsGroupId).toBe("CJU_RNMVS");
  });

  it("mantém a seleção da Exposição isolada do AnalysisProvider", async () => {
    vi.mocked(fetchExposureAssets).mockResolvedValue([wind, solar]);
    vi.mocked(fetchExposureView).mockResolvedValue(exposureView(solar));
    // The provider must work on its own: no AnalysisProvider is mounted here.
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(result.current.assets).toHaveLength(2));
    act(() => result.current.selectAsset("RNMVS2"));

    await waitFor(() => expect(result.current.selectedAssetId).toBe("RNMVS2"));
    expect(Object.keys(result.current).sort()).toEqual(
      ["assets", "error", "loading", "retry", "selectAsset", "selectedAssetId", "view"].sort(),
    );
  });
});
