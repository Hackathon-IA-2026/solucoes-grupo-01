import { z } from "zod";
import type {
  ExposureAsset,
  ExposureCriticalWindow,
  ExposureForecastPoint,
  ExposureForecastProbabilityStatus,
  ExposureForecastWindow,
  ExposureNarrative,
  ExposurePointContext,
  ExposureSimulatedTelemetry,
  ExposureView,
  ExposureWireEntityStatus,
  ExposureWireOrigin,
} from "~/domain/types";

/**
 * The demonstration is fixed on five verified individual plants. The Exposição
 * catalog must contain exactly these entries; generation groups (`CJU_*`) are
 * never selectable here.
 */
export const VERIFIED_EXPOSURE_PLANT_IDS = ["RNEM13", "BAEA52", "BAEB0B", "RNMVS2", "PBLZ3"] as const;

const VERIFIED_PLANT_ID_SET: ReadonlySet<string> = new Set(VERIFIED_EXPOSURE_PLANT_IDS);
const DAY_MS = 86_400_000;
const WINDOW_MS = 72 * 3_600_000;

const originValues = ["SIMULADO", "OBSERVADO"] as const;
const entityStatusValues = ["simulated", "observed"] as const;
const originSchema = z.enum(originValues) satisfies z.ZodType<ExposureWireOrigin>;
const entityStatusSchema = z.enum(entityStatusValues) satisfies z.ZodType<ExposureWireEntityStatus>;

/** ISO 8601 date-time that tolerates a missing UTC offset (backend may omit it). */
const isoDateTimeSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/, "Data e hora em formato ISO 8601");

const metricSchema = z.object({ value: z.number().finite().nullable(), unit: z.string().min(1) }).strict();
const distributionSchema = z.object({ label: z.string().min(1), value: z.number().finite() }).strict();

const plantIdSchema = z
  .string()
  .min(1)
  .max(64)
  .refine((value) => !value.startsWith("CJU_"), "O identificador da usina não pode ser um conjunto gerador.");

const assetSchema = z
  .object({
    asset_id: plantIdSchema,
    name: z.string().min(1),
    entity_level: z.literal("plant"),
    technology: z.enum(["wind", "solar"]),
    state: z.string().length(2),
    connection_point: z.string().min(1),
    capacity_mw: z.number().finite().nullable(),
    connected_asset_count: z.number().int().nonnegative(),
    operational_data_status: z.enum(["simulated", "client_connected"]),
    allocation_coverage: metricSchema.nullable().optional(),
    ons_group_id: z.string().min(1).max(64).nullable().optional(),
    ons_group_name: z.string().min(1).nullable().optional(),
    ceg: z.string().min(1).nullable().optional(),
  })
  .strict();

const pointEntitySchema = z
  .object({
    plant_id: plantIdSchema,
    name: z.string().min(1),
    technology: z.enum(["wind", "solar"]),
    ons_group_id: z.string().min(1).max(64),
    capacity_mw: z.number().finite().nonnegative(),
    mean_available_generation_mw: z.number().finite().nonnegative(),
    mean_curtailed_generation_mw: z.number().finite().nonnegative(),
    restricted_day_share: z.number().finite().min(0).max(1),
    scheduled_maintenance_intervals: z.number().int().nonnegative(),
    scheduled_maintenance_derate: z.number().finite().gt(0).max(1),
    // Validated wire status/source; never mapped into the rendered view.
    operational_data_status: entityStatusSchema,
    origin: originSchema,
  })
  .strict();

const pointContextSchema = z
  .object({
    point_id: z.string().min(1),
    entity_count: z.number().int().min(1).max(512),
    installed_capacity_mw: z.number().finite().nonnegative(),
    potential_generation_mw: z.number().finite().nonnegative(),
    accepted_generation_envelope_mw: z.number().finite().nonnegative(),
    estimated_excess_mw: z.number().finite().nonnegative(),
    scheduled_maintenance_relief_mw: z.number().finite().nonnegative(),
    envelope: z
      .object({
        intercept_mw: z.number().finite().nonnegative(),
        slope: z.number().finite().min(0).max(1),
      })
      .strict(),
    scheduled_maintenance_window_count: z.number().int().nonnegative(),
    simulated_entities: z.array(pointEntitySchema).max(512),
    // Validated wire source; never mapped into the rendered view.
    origin: originSchema,
  })
  .strict();

const simulatedTelemetrySchema = z
  .object({
    generation_mw: z.number().finite().nonnegative(),
    potential_generation_mw: z.number().finite().nonnegative(),
    availability_mw: z.number().finite().nonnegative(),
    operational_capacity_mw: z.number().finite().nonnegative(),
    accepted_generation_limit_mw: z.number().finite().nonnegative(),
    potentially_curtailed_mw: z.number().finite().nonnegative(),
    restricted: z.boolean(),
    weather_value: z.number().finite(),
    weather_unit: z.string().min(1).max(16),
    // Validated wire source; never mapped into the rendered view.
    origin: originSchema,
  })
  .strict();

const forecastPointSchema = z
  .object({
    forecast_date: z.string().date(),
    display_label: z.string().regex(/^\d{2}\/\d{2}$/, "O rótulo diário deve seguir DD/MM"),
    expected_curtailed_mwh: z.number().finite().nonnegative(),
    lower_mwh: z.number().finite().nonnegative(),
    upper_mwh: z.number().finite().nonnegative(),
    curtailment_probability: z.number().finite().min(0).max(1),
    potential_generation_mwh: z.number().finite().nonnegative(),
    accepted_generation_envelope_mwh: z.number().finite().nonnegative(),
    scheduled_maintenance_relief_mwh: z.number().finite().nonnegative(),
    avoided_curtailment_mwh: z.number().finite().nonnegative(),
    risk_reduction_percentage_points: z.number().finite(),
  })
  .strict()
  .superRefine((point, context) => {
    if (!(point.lower_mwh <= point.expected_curtailed_mwh && point.expected_curtailed_mwh <= point.upper_mwh)) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Faixa estimada inválida" });
    }
    if (point.accepted_generation_envelope_mwh > point.potential_generation_mwh) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "O envelope aceito não pode exceder a geração potencial",
      });
    }
    const [, month, day] = point.forecast_date.split("-");
    if (point.display_label !== `${day}/${month}`) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Rótulo diário incompatível com a data" });
    }
  });

/** Base window shape, also used for the tolerated legacy weekly highlight list. */
const forecastWindowSchema = z
  .object({
    start: z.string().date(),
    end: z.string().date(),
    expected_curtailed_mwh: z.number().finite().nonnegative(),
    mean_probability: z.number().finite().min(0).max(1),
    rank: z.number().int().min(1).max(3).nullable().optional(),
    starts_at: isoDateTimeSchema.nullable().optional(),
    ends_at: isoDateTimeSchema.nullable().optional(),
    interval_count: z.number().int().positive().nullable().optional(),
    window_hours: z.number().finite().positive().nullable().optional(),
    curtailment_probability: z.number().finite().min(0).max(1).nullable().optional(),
    scheduled_maintenance_relief_mwh: z.number().finite().nonnegative().nullable().optional(),
    avoided_curtailment_mwh: z.number().finite().nonnegative().nullable().optional(),
    candidate_maintenance_relief_mwh: z.number().finite().nonnegative().nullable().optional(),
  })
  .strict();

const criticalWindowSchema = z
  .object({
    rank: z.number().int().min(1).max(3),
    starts_at: isoDateTimeSchema,
    ends_at: isoDateTimeSchema,
    start: z.string().date(),
    end: z.string().date(),
    expected_curtailed_mwh: z.number().finite().nonnegative(),
    mean_probability: z.number().finite().min(0).max(1),
    interval_count: z.number().int().positive(),
    window_hours: z.number().finite().positive(),
    curtailment_probability: z.number().finite().min(0).max(1),
    scheduled_maintenance_relief_mwh: z.number().finite().nonnegative(),
    avoided_curtailment_mwh: z.number().finite().nonnegative(),
    candidate_maintenance_relief_mwh: z.number().finite().nonnegative().nullable(),
  })
  .strict();

const probabilityStatusValues = [
  "empirical_uncalibrated",
  "backtested_calibrated",
  "backtested_empirical_uncalibrated",
  "baseline_historical_frequency",
  "unavailable",
] as const;

const forecastSchema = z
  .object({
    status: z.enum(["demonstrative_simulation", "unavailable"]),
    start: z.string().date().nullable(),
    end: z.string().date().nullable(),
    points: z.array(forecastPointSchema).max(60),
    total_expected_mwh: z.number().finite().nonnegative().nullable(),
    total_lower_mwh: z.number().finite().nonnegative().nullable(),
    total_upper_mwh: z.number().finite().nonnegative().nullable(),
    event_threshold_mwh: z.number().finite().nonnegative().nullable(),
    event_percentile: z.number().finite().min(0).max(1).nullable(),
    probability_status: z.enum(probabilityStatusValues) satisfies z.ZodType<ExposureForecastProbabilityStatus>,
    // Technical metadata accepted from the wire and intentionally not mapped.
    probability_source: z.string().min(1).nullable().optional(),
    simulation_method: z.string().min(1).max(64).nullable().optional(),
    window_definition: z.string().min(1).nullable().optional(),
    top_windows: z.array(forecastWindowSchema).max(3).optional(),
    critical_windows_72h: z.array(criticalWindowSchema).max(3).optional(),
  })
  .strict()
  .superRefine((forecast, context) => {
    const windows = forecast.critical_windows_72h ?? [];
    if (forecast.status === "unavailable") {
      if (forecast.points.length !== 0 || forecast.start !== null || forecast.end !== null || windows.length !== 0) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "A previsão indisponível não pode conter horizonte nem janelas",
        });
      }
      return;
    }
    if (forecast.points.length !== 60 || forecast.start === null || forecast.end === null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A previsão demonstrativa exige 60 dias datados",
      });
      return;
    }
    const days = forecast.points.map((point) => Date.parse(`${point.forecast_date}T00:00:00Z`));
    for (let index = 1; index < days.length; index += 1) {
      if (days[index] - days[index - 1] !== DAY_MS) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "As datas da previsão devem ser dias consecutivos",
        });
        break;
      }
    }
    if (forecast.points[0].forecast_date !== forecast.start || forecast.points[59].forecast_date !== forecast.end) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Os limites da previsão devem coincidir com o primeiro e o último dia",
      });
    }
    if (
      forecast.event_threshold_mwh === null ||
      forecast.event_percentile === null ||
      forecast.probability_status === "unavailable"
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A previsão demonstrativa exige a definição do evento material",
      });
    }
    const { total_lower_mwh: lower, total_expected_mwh: expected, total_upper_mwh: upper } = forecast;
    if (lower === null || expected === null || upper === null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A previsão demonstrativa exige os totais da faixa estimada",
      });
    } else if (!(lower <= expected && expected <= upper)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A faixa acumulada deve conter o valor esperado",
      });
    }
    if (windows.length !== 3) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A previsão demonstrativa exige exatamente três janelas críticas de 72 horas",
      });
      return;
    }
    if (new Set(windows.map((window) => window.rank)).size !== 3) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "As janelas críticas exigem ranks distintos" });
    }
    const horizonStart = forecast.start;
    const horizonEnd = forecast.end;
    const ordered = [...windows].sort((left, right) => Date.parse(left.starts_at) - Date.parse(right.starts_at));
    ordered.forEach((window, index) => {
      if (window.interval_count !== 144 || window.window_hours !== 72) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Cada janela crítica deve cobrir 144 intervalos de meia hora (72 horas)",
        });
      }
      if (Date.parse(window.ends_at) - Date.parse(window.starts_at) !== WINDOW_MS) {
        context.addIssue({ code: z.ZodIssueCode.custom, message: "Cada janela crítica deve durar 72 horas" });
      }
      if (window.start < horizonStart || window.end > horizonEnd) {
        context.addIssue({ code: z.ZodIssueCode.custom, message: "A janela crítica deve estar no horizonte previsto" });
      }
      if (index > 0 && Date.parse(window.starts_at) < Date.parse(ordered[index - 1].ends_at)) {
        context.addIssue({ code: z.ZodIssueCode.custom, message: "As janelas críticas não podem se sobrepor" });
      }
    });
  });

/**
 * Narrative schema, isolated from plant/forecast/window validation.
 *
 * The API serves one section object per column with `paragraphs` plus the
 * internal `generation_mode`. The mode is validated here and then dropped by
 * `mapNarrative`, so Bedrock, cache and deterministic fallback share the same
 * title and are never labelled on screen.
 */
const sectionIds = ["secao-ativo", "secao-resumo", "secao-previsao", "secao-razao-origem", "secao-recorrencia", "secao-qualidade"] as const;

export const exposureNarrativeSectionSchema = z
  .object({
    paragraphs: z.array(z.string().min(1)).min(1).max(4),
    generation_mode: z.enum(["bedrock", "cached_bedrock", "deterministic_fallback"]),
  })
  .strict();

export const exposureNarrativeSchema = z
  .object(
    Object.fromEntries(
      sectionIds.map((id) => [id, exposureNarrativeSectionSchema]),
    ) as Record<(typeof sectionIds)[number], typeof exposureNarrativeSectionSchema>,
  )
  .strict();

export const exposureViewSchema = z
  .object({
    asset: assetSchema,
    last_data_update: z.string().datetime({ offset: true }),
    input_digest: z.string().regex(/^[a-f0-9]{64}$/),
    observed_impact: z
      .object({
        total_curtailed_energy: metricSchema,
        event_day_share: metricSchema,
        latest_daily_curtailed_energy: metricSchema,
        trailing_7_day_mean: metricSchema,
        trailing_30_day_mean: metricSchema,
        characterized_share: metricSchema,
        simultaneous_share: metricSchema,
        exclusive_share: metricSchema,
        curtailed_day_share: metricSchema.nullable().optional(),
        allocation_coverage: metricSchema.nullable().optional(),
        period_start: z.string().date(),
        period_end: z.string().date(),
      })
      .strict(),
    forecast_60d: forecastSchema,
    associated_conditions: z
      .object({
        reasons: z.array(distributionSchema),
        origins: z.array(distributionSchema),
        modalities: z.array(distributionSchema),
      })
      .strict(),
    recurrence: z
      .object({
        timezone: z.literal("America/Sao_Paulo"),
        weekdays: z.array(distributionSchema),
        hours: z.array(distributionSchema),
      })
      .strict(),
    quality: z
      .object({
        coverage: metricSchema,
        update_delay: metricSchema,
        missing_rate: metricSchema,
        duplicate_count: metricSchema,
      })
      .strict(),
    narrative: exposureNarrativeSchema,
    limitations: z.array(z.string().min(1)),
    point_context: pointContextSchema.nullable().optional(),
    simulated_telemetry: simulatedTelemetrySchema.nullable().optional(),
  })
  .strict();

export const exposureCatalogSchema = z
  .object({ items: z.array(assetSchema).min(1).max(5) })
  .strict()
  .superRefine((catalog, context) => {
    const identifiers = catalog.items.map((item) => item.asset_id);
    if (new Set(identifiers).size !== identifiers.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "O catálogo não pode repetir usinas" });
    }
    if (
      identifiers.length !== VERIFIED_EXPOSURE_PLANT_IDS.length ||
      !identifiers.every((identifier) => VERIFIED_PLANT_ID_SET.has(identifier))
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "O catálogo deve conter exatamente as cinco usinas verificadas",
      });
    }
  });

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
    entityLevel: raw.entity_level,
    technology: raw.technology,
    state: raw.state,
    connectionPoint: raw.connection_point,
    capacityMw: raw.capacity_mw,
    connectedAssetCount: raw.connected_asset_count,
    operationalDataStatus: raw.operational_data_status,
    allocationCoverage: raw.allocation_coverage ?? null,
    onsGroupId: raw.ons_group_id ?? null,
    onsGroupName: raw.ons_group_name ?? null,
    ceg: raw.ceg ?? null,
  };
}

function mapForecastPoint(raw: z.infer<typeof forecastPointSchema>): ExposureForecastPoint {
  return {
    forecastDate: raw.forecast_date,
    displayLabel: raw.display_label,
    expectedCurtailedMwh: raw.expected_curtailed_mwh,
    lowerMwh: raw.lower_mwh,
    upperMwh: raw.upper_mwh,
    curtailmentProbability: raw.curtailment_probability,
    potentialGenerationMwh: raw.potential_generation_mwh,
    acceptedGenerationEnvelopeMwh: raw.accepted_generation_envelope_mwh,
    scheduledMaintenanceReliefMwh: raw.scheduled_maintenance_relief_mwh,
    avoidedCurtailmentMwh: raw.avoided_curtailment_mwh,
    riskReductionPercentagePoints: raw.risk_reduction_percentage_points,
  };
}

function mapForecastWindow(raw: z.infer<typeof forecastWindowSchema>): ExposureForecastWindow {
  return {
    start: raw.start,
    end: raw.end,
    expectedCurtailedMwh: raw.expected_curtailed_mwh,
    meanProbability: raw.mean_probability,
  };
}

function mapCriticalWindow(raw: z.infer<typeof criticalWindowSchema>): ExposureCriticalWindow {
  return {
    start: raw.start,
    end: raw.end,
    expectedCurtailedMwh: raw.expected_curtailed_mwh,
    meanProbability: raw.mean_probability,
    rank: raw.rank,
    startsAt: raw.starts_at,
    endsAt: raw.ends_at,
    intervalCount: raw.interval_count,
    windowHours: raw.window_hours,
    curtailmentProbability: raw.curtailment_probability,
    scheduledMaintenanceReliefMwh: raw.scheduled_maintenance_relief_mwh,
    avoidedCurtailmentMwh: raw.avoided_curtailment_mwh,
    candidateMaintenanceReliefMwh: raw.candidate_maintenance_relief_mwh ?? null,
  };
}

function mapPointContext(raw: z.infer<typeof pointContextSchema>): ExposurePointContext {
  return {
    pointId: raw.point_id,
    entityCount: raw.entity_count,
    installedCapacityMw: raw.installed_capacity_mw,
    potentialGenerationMw: raw.potential_generation_mw,
    acceptedGenerationEnvelopeMw: raw.accepted_generation_envelope_mw,
    estimatedExcessMw: raw.estimated_excess_mw,
    scheduledMaintenanceReliefMw: raw.scheduled_maintenance_relief_mw,
    envelopeInterceptMw: raw.envelope.intercept_mw,
    envelopeSlope: raw.envelope.slope,
    scheduledMaintenanceWindowCount: raw.scheduled_maintenance_window_count,
    entities: raw.simulated_entities.map((entity) => ({
      plantId: entity.plant_id,
      name: entity.name,
      technology: entity.technology,
      onsGroupId: entity.ons_group_id,
      capacityMw: entity.capacity_mw,
      meanAvailableGenerationMw: entity.mean_available_generation_mw,
      meanCurtailedGenerationMw: entity.mean_curtailed_generation_mw,
      restrictedDayShare: entity.restricted_day_share,
      scheduledMaintenanceIntervals: entity.scheduled_maintenance_intervals,
      scheduledMaintenanceDerate: entity.scheduled_maintenance_derate,
    })),
  };
}

function mapSimulatedTelemetry(raw: z.infer<typeof simulatedTelemetrySchema>): ExposureSimulatedTelemetry {
  return {
    generationMw: raw.generation_mw,
    potentialGenerationMw: raw.potential_generation_mw,
    availabilityMw: raw.availability_mw,
    operationalCapacityMw: raw.operational_capacity_mw,
    acceptedGenerationLimitMw: raw.accepted_generation_limit_mw,
    potentiallyCurtailedMw: raw.potentially_curtailed_mw,
    restricted: raw.restricted,
    weatherValue: raw.weather_value,
    weatherUnit: raw.weather_unit,
  };
}

/**
 * Keeps only the validated paragraphs of each section. The wire
 * `generation_mode` is intentionally discarded so the interface cannot
 * distinguish Bedrock, cache and deterministic fallback.
 */
function mapNarrative(raw: z.infer<typeof exposureNarrativeSchema>): ExposureNarrative {
  return {
    "secao-ativo": [...raw["secao-ativo"].paragraphs],
    "secao-resumo": [...raw["secao-resumo"].paragraphs],
    "secao-previsao": [...raw["secao-previsao"].paragraphs],
    "secao-razao-origem": [...raw["secao-razao-origem"].paragraphs],
    "secao-recorrencia": [...raw["secao-recorrencia"].paragraphs],
    "secao-qualidade": [...raw["secao-qualidade"].paragraphs],
  };
}

export async function fetchExposureAssets(signal?: AbortSignal): Promise<ExposureAsset[]> {
  const raw = exposureCatalogSchema.parse(await getJson("/v1/exposure/assets", signal));
  return raw.items.map(mapAsset);
}

export async function fetchExposureView(assetId: string, signal?: AbortSignal): Promise<ExposureView> {
  const raw = exposureViewSchema.parse(await getJson(`/v1/assets/${encodeURIComponent(assetId)}/exposure-view`, signal));
  return {
    asset: mapAsset(raw.asset),
    lastDataUpdate: raw.last_data_update,
    inputDigest: raw.input_digest,
    observedImpact: {
      totalCurtailedEnergy: raw.observed_impact.total_curtailed_energy,
      eventDayShare: raw.observed_impact.event_day_share,
      latestDailyCurtailedEnergy: raw.observed_impact.latest_daily_curtailed_energy,
      trailing7DayMean: raw.observed_impact.trailing_7_day_mean,
      trailing30DayMean: raw.observed_impact.trailing_30_day_mean,
      characterizedShare: raw.observed_impact.characterized_share,
      simultaneousShare: raw.observed_impact.simultaneous_share,
      exclusiveShare: raw.observed_impact.exclusive_share,
      curtailedDayShare: raw.observed_impact.curtailed_day_share ?? null,
      allocationCoverage: raw.observed_impact.allocation_coverage ?? null,
      periodStart: raw.observed_impact.period_start,
      periodEnd: raw.observed_impact.period_end,
    },
    forecast60d: {
      status: raw.forecast_60d.status,
      start: raw.forecast_60d.start,
      end: raw.forecast_60d.end,
      points: raw.forecast_60d.points.map(mapForecastPoint),
      totalExpectedMwh: raw.forecast_60d.total_expected_mwh,
      totalLowerMwh: raw.forecast_60d.total_lower_mwh,
      totalUpperMwh: raw.forecast_60d.total_upper_mwh,
      eventThresholdMwh: raw.forecast_60d.event_threshold_mwh,
      eventPercentile: raw.forecast_60d.event_percentile,
      probabilityStatus: raw.forecast_60d.probability_status,
      topWindows: (raw.forecast_60d.top_windows ?? []).map(mapForecastWindow),
      criticalWindows72h: (raw.forecast_60d.critical_windows_72h ?? []).map(mapCriticalWindow),
    },
    associatedConditions: raw.associated_conditions,
    recurrence: raw.recurrence,
    quality: {
      coverage: raw.quality.coverage,
      updateDelay: raw.quality.update_delay,
      missingRate: raw.quality.missing_rate,
      duplicateCount: raw.quality.duplicate_count,
    },
    pointContext: raw.point_context ? mapPointContext(raw.point_context) : null,
    simulatedTelemetry: raw.simulated_telemetry ? mapSimulatedTelemetry(raw.simulated_telemetry) : null,
    narrative: mapNarrative(raw.narrative),
    limitations: raw.limitations,
  };
}
