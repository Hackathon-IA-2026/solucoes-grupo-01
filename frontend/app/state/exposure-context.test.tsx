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
  assetId: "CJU_RNRDV",
  name: "Conj. Rio do Vento",
  technology: "wind",
  state: "RN",
  connectionPoint: "RNCMM-500-A",
  capacityMw: null,
  connectedAssetCount: 1,
  operationalDataStatus: "simulated",
};
const solar: ExposureAsset = {
  ...wind,
  assetId: "CJU_RNMVS",
  name: "Conj. Monte Verde Solar",
  technology: "solar",
  connectionPoint: "RNMTV-500-A",
  connectedAssetCount: 3,
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
      topWindows: [],
    },
    associatedConditions: { reasons: [], origins: [], modalities: [] },
    recurrence: { timezone: "America/Sao_Paulo", weekdays: [], hours: [] },
    quality: {
      coverage: unavailable,
      updateDelay: { value: null, unit: "dias" },
      missingRate: unavailable,
      duplicateCount: { value: null, unit: "intervalos" },
    },
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
  it("cancela a resposta anterior ao trocar de ativo", async () => {
    const first = deferred<ExposureView>();
    vi.mocked(fetchExposureAssets).mockResolvedValue([wind, solar]);
    vi.mocked(fetchExposureView)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(exposureView(solar));
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(fetchExposureView).toHaveBeenCalledWith("CJU_RNRDV", expect.any(AbortSignal)));
    const firstSignal = vi.mocked(fetchExposureView).mock.calls[0][1];
    act(() => result.current.selectAsset("CJU_RNMVS"));

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("CJU_RNMVS"));
    expect(firstSignal?.aborted).toBe(true);
    first.resolve(exposureView(wind));
    await Promise.resolve();
    expect(result.current.view?.asset.assetId).toBe("CJU_RNMVS");
  });

  it("repete o catálogo após uma falha completa", async () => {
    vi.mocked(fetchExposureAssets)
      .mockRejectedValueOnce(new Error("falha de rede"))
      .mockResolvedValueOnce([wind]);
    vi.mocked(fetchExposureView).mockResolvedValue(exposureView(wind));
    const { result } = renderHook(() => useExposure(), { wrapper: ExposureProvider });

    await waitFor(() => expect(result.current.error).toBe("falha de rede"));
    act(() => result.current.retry());

    await waitFor(() => expect(result.current.view?.asset.assetId).toBe("CJU_RNRDV"));
    expect(fetchExposureAssets).toHaveBeenCalledTimes(2);
  });
});
