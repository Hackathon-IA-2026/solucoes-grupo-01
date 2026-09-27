import { z } from "zod";
import type { ExposureAsset, ExposureNarrative, ExposureView } from "~/domain/types";

const metricSchema = z.object({ value: z.number().finite().nullable(), unit: z.string().min(1) }).strict();
const distributionSchema = z.object({ label: z.string().min(1), value: z.number().finite() }).strict();
const assetSchema = z.object({
  asset_id: z.string().min(1),
  name: z.string().min(1),
  technology: z.enum(["wind", "solar"]),
  state: z.string().length(2),
  connection_point: z.string().min(1),
  capacity_mw: z.number().finite().nullable(),
  connected_asset_count: z.number().int().nonnegative(),
  operational_data_status: z.enum(["simulated", "client_connected"]),
}).strict();
const forecastPointSchema = z.object({
  forecast_date: z.string().date(),
  expected_curtailed_mwh: z.number().finite().nonnegative(),
  lower_mwh: z.number().finite().nonnegative(),
  upper_mwh: z.number().finite().nonnegative(),
  curtailment_probability: z.number().finite().min(0).max(1),
}).strict().refine((point) => point.lower_mwh <= point.expected_curtailed_mwh && point.expected_curtailed_mwh <= point.upper_mwh, "Faixa estimada inválida");
const forecastWindowSchema = z.object({
  start: z.string().date(),
  end: z.string().date(),
  expected_curtailed_mwh: z.number().finite().nonnegative(),
  mean_probability: z.number().finite().min(0).max(1),
}).strict();
const sectionIds = ["secao-ativo", "secao-resumo", "secao-previsao", "secao-razao-origem", "secao-recorrencia", "secao-qualidade"] as const;
const narrativeSchema = z.object(Object.fromEntries(sectionIds.map((id) => [id, z.array(z.string().min(1)).min(1).max(4)])) as Record<(typeof sectionIds)[number], z.ZodArray<z.ZodString>>).strict();
const viewSchema = z.object({
  asset: assetSchema,
  last_data_update: z.string().datetime({ offset: true }),
  input_digest: z.string().regex(/^[a-f0-9]{64}$/),
  observed_impact: z.object({
    total_curtailed_energy: metricSchema,
    characterized_share: metricSchema,
    simultaneous_share: metricSchema,
    exclusive_share: metricSchema,
    period_start: z.string().date(),
    period_end: z.string().date(),
  }).strict(),
  forecast_60d: z.object({
    status: z.enum(["demonstrative_simulation", "unavailable"]),
    start: z.string().date().nullable(),
    end: z.string().date().nullable(),
    points: z.array(forecastPointSchema).max(60),
    total_expected_mwh: z.number().finite().nonnegative().nullable(),
    total_lower_mwh: z.number().finite().nonnegative().nullable(),
    total_upper_mwh: z.number().finite().nonnegative().nullable(),
    top_windows: z.array(forecastWindowSchema).max(3),
  }).strict().superRefine((forecast, context) => {
    if (forecast.status === "demonstrative_simulation" && forecast.points.length !== 60) context.addIssue({ code: z.ZodIssueCode.custom, message: "A previsão demonstrativa exige 60 pontos" });
  }),
  associated_conditions: z.object({ reasons: z.array(distributionSchema), origins: z.array(distributionSchema), modalities: z.array(distributionSchema) }).strict(),
  recurrence: z.object({ timezone: z.literal("America/Sao_Paulo"), weekdays: z.array(distributionSchema), hours: z.array(distributionSchema) }).strict(),
  quality: z.object({ coverage: metricSchema, update_delay: metricSchema, missing_rate: metricSchema, duplicate_count: metricSchema }).strict(),
  narrative: narrativeSchema,
  limitations: z.array(z.string().min(1)),
}).strict();
const catalogSchema = z.object({ items: z.array(assetSchema).min(1).max(5) }).strict();

function apiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!configured) return "http://127.0.0.1:8000";
  return configured.replace(/\/$/, "");
}

async function getJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`${apiBaseUrl()}${path}`, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`A API respondeu com HTTP ${response.status}.`);
  return response.json();
}

function mapAsset(raw: z.infer<typeof assetSchema>): ExposureAsset {
  return {
    assetId: raw.asset_id,
    name: raw.name,
    technology: raw.technology,
    state: raw.state,
    connectionPoint: raw.connection_point,
    capacityMw: raw.capacity_mw,
    connectedAssetCount: raw.connected_asset_count,
    operationalDataStatus: raw.operational_data_status,
  };
}

export async function fetchExposureAssets(signal?: AbortSignal): Promise<ExposureAsset[]> {
  const raw = catalogSchema.parse(await getJson("/v1/exposure/assets", signal));
  return raw.items.map(mapAsset);
}

export async function fetchExposureView(assetId: string, signal?: AbortSignal): Promise<ExposureView> {
  const raw = viewSchema.parse(await getJson(`/v1/assets/${encodeURIComponent(assetId)}/exposure-view`, signal));
  return {
    asset: mapAsset(raw.asset),
    lastDataUpdate: raw.last_data_update,
    inputDigest: raw.input_digest,
    observedImpact: {
      totalCurtailedEnergy: raw.observed_impact.total_curtailed_energy,
      characterizedShare: raw.observed_impact.characterized_share,
      simultaneousShare: raw.observed_impact.simultaneous_share,
      exclusiveShare: raw.observed_impact.exclusive_share,
      periodStart: raw.observed_impact.period_start,
      periodEnd: raw.observed_impact.period_end,
    },
    forecast60d: {
      status: raw.forecast_60d.status,
      start: raw.forecast_60d.start,
      end: raw.forecast_60d.end,
      points: raw.forecast_60d.points.map((point) => ({
        forecastDate: point.forecast_date,
        expectedCurtailedMwh: point.expected_curtailed_mwh,
        lowerMwh: point.lower_mwh,
        upperMwh: point.upper_mwh,
        curtailmentProbability: point.curtailment_probability,
      })),
      totalExpectedMwh: raw.forecast_60d.total_expected_mwh,
      totalLowerMwh: raw.forecast_60d.total_lower_mwh,
      totalUpperMwh: raw.forecast_60d.total_upper_mwh,
      topWindows: raw.forecast_60d.top_windows.map((window) => ({
        start: window.start,
        end: window.end,
        expectedCurtailedMwh: window.expected_curtailed_mwh,
        meanProbability: window.mean_probability,
      })),
    },
    associatedConditions: raw.associated_conditions,
    recurrence: raw.recurrence,
    quality: {
      coverage: raw.quality.coverage,
      updateDelay: raw.quality.update_delay,
      missingRate: raw.quality.missing_rate,
      duplicateCount: raw.quality.duplicate_count,
    },
    narrative: raw.narrative as ExposureNarrative,
    limitations: raw.limitations,
  };
}
