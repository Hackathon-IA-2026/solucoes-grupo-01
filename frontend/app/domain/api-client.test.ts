import { afterEach, describe, expect, it, vi } from "vitest";
import { createCurtaiLessApi, mapNumericEvidence } from "./api-client";

afterEach(() => vi.restoreAllMocks());

describe("cliente da API CurtaiLess", () => {
  it("preserva metadados de evidência e converte o estado público", () => {
    expect(mapNumericEvidence({ value: 6, unit: "entities", period: { start: "2026-08-01", end: "2026-08-31" }, source: "ONS/usina_conjunto", data_version: "2026-08", method: "point_context_v1", value_status: "calculado", limitations: ["limite"], provenance_id: "sha256:abc" })).toEqual(expect.objectContaining({ value: 6, unit: "entities", state: "calculado", source: "ONS/usina_conjunto", dataVersion: "2026-08", method: "point_context_v1" }));
  });

  it("carrega ativos materializados e converte o contrato público para a interface", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        asset_id: "CJU_BABAB",
        name: "Conj. Babilônia",
        technology: "wind",
        capacity_mw: null,
        ons_group: "CJU_BABAB",
        connection_point: "BAMPD-230-A",
        data_mode: "ons_materialized",
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const api = createCurtaiLessApi("https://api.example/dev/", fetcher);
    await expect(api.listAssets()).resolves.toEqual([{ id: "CJU_BABAB", name: "Conj. Babilônia", technology: "Eólica", location: "Não informada pelo ONS", connectionPoint: "BAMPD-230-A", anonymousEntities: 0, telemetry: "ausente", dataMode: "ons_materialized" }]);
    expect(fetcher).toHaveBeenCalledWith("https://api.example/dev/v1/assets", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("carrega exposição, contexto do ponto e janelas pelos endpoints por ativo", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ asset_id: "A", total_curtailed_energy: { value: 9304.1 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ asset_id: "A", anonymized_entity_count: { value: 6 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ asset_id: "A", windows: [] }), { status: 200 }));
    const api = createCurtaiLessApi("https://api.example/dev", fetcher);

    await api.getExposure("A", "2026-08-01", "2026-08-31");
    await api.getPointContext("A");
    await api.getWindows("A", "2026-08-01", "2026-08-31", 72);

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example/dev/v1/assets/A/exposure?start=2026-08-01&end=2026-08-31",
      "https://api.example/dev/v1/assets/A/point-context",
      "https://api.example/dev/v1/assets/A/windows?start=2026-08-01&end=2026-08-31&duration_hours=72",
    ]);
  });

  it("rejeita respostas HTTP com mensagem controlada", async () => {
    const api = createCurtaiLessApi("https://api.example/dev", vi.fn().mockResolvedValue(new Response("indisponível", { status: 503 })));
    await expect(api.listAssets()).rejects.toThrow("API CurtaiLess respondeu com HTTP 503");
  });

  it("exige URL explícita da API", () => {
    expect(() => createCurtaiLessApi("  ")).toThrow("VITE_API_BASE_URL não configurada");
  });
});
