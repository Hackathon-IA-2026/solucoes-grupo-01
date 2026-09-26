import type { Asset, EvidenceState, EvidenceValue } from "./types";

type ApiAsset = {
  asset_id: string;
  name: string;
  technology: "wind" | "solar";
  capacity_mw: number | null;
  ons_group: string;
  connection_point: string;
  data_mode: "demo" | "ons_materialized";
};

type ApiAssetList = { items: ApiAsset[] };
export type ApiNumericEvidence = {
  value: number;
  unit: string;
  period: { start: string; end: string };
  source: string;
  data_version: string;
  method: string;
  value_status: "medido" | "calculado" | "previsto" | "simulado" | "informado";
  limitations: string[];
  provenance_id: string;
};
export type ApiExposure = { asset_id: string; perspective_type: "historical_observed"; data_mode: "demo" | "ons_materialized"; total_curtailed_energy: ApiNumericEvidence; limitations: string[] };
export type ApiPointContext = { asset_id: string; connection_point: string; data_mode: "demo" | "ons_materialized"; anonymized_entity_count: ApiNumericEvidence; simultaneity_rate: ApiNumericEvidence; physical_limit_available: boolean; limitations: string[] };
export type ApiHistoricalWindows = { asset_id: string; perspective_type: "historical_seasonal"; validation_status: "historical_signal"; data_mode: "demo" | "ons_materialized"; duration_hours: number; windows: Array<{ start: string; end: string; expected_curtailed_energy: ApiNumericEvidence }>; limitations: string[] };
type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

const evidenceState: Record<ApiNumericEvidence["value_status"], EvidenceState> = {
  medido: "medido",
  calculado: "calculado",
  previsto: "previsto",
  simulado: "simulado",
  informado: "informado pelo cliente",
};

export function mapNumericEvidence(evidence: ApiNumericEvidence): EvidenceValue {
  return {
    value: evidence.value,
    unit: evidence.unit,
    period: { ...evidence.period, label: `${evidence.period.start} a ${evidence.period.end}` },
    source: evidence.source,
    dataVersion: evidence.data_version,
    method: evidence.method,
    state: evidenceState[evidence.value_status],
    unavailableReason: evidence.limitations.join(" ") || undefined,
  };
}

function mapAsset(asset: ApiAsset): Asset {
  return {
    id: asset.asset_id,
    name: asset.name,
    technology: asset.technology === "solar" ? "Solar" : "Eólica",
    location: "Não informada pelo ONS",
    connectionPoint: asset.connection_point,
    anonymousEntities: 0,
    telemetry: "ausente",
    dataMode: asset.data_mode,
  };
}

export function createCurtaiLessApi(baseUrl: string, fetcher: Fetcher = fetch) {
  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
  if (!normalizedBaseUrl) throw new Error("VITE_API_BASE_URL não configurada");

  async function get<T>(path: string): Promise<T> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`API CurtaiLess respondeu com HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }

  const params = (start: string, end: string) => new URLSearchParams({ start, end }).toString();

  return {
    async listAssets(): Promise<Asset[]> {
      const response = await get<ApiAssetList>("/v1/assets");
      return response.items.map(mapAsset);
    },
    getExposure(assetId: string, start: string, end: string): Promise<ApiExposure> {
      return get(`/v1/assets/${encodeURIComponent(assetId)}/exposure?${params(start, end)}`);
    },
    getPointContext(assetId: string): Promise<ApiPointContext> {
      return get(`/v1/assets/${encodeURIComponent(assetId)}/point-context`);
    },
    getWindows(assetId: string, start: string, end: string, durationHours = 72): Promise<ApiHistoricalWindows> {
      const query = new URLSearchParams({ start, end, duration_hours: String(durationHours) });
      return get(`/v1/assets/${encodeURIComponent(assetId)}/windows?${query.toString()}`);
    },
  };
}

export function getConfiguredCurtaiLessApi() {
  return createCurtaiLessApi(import.meta.env.VITE_API_BASE_URL ?? "");
}
