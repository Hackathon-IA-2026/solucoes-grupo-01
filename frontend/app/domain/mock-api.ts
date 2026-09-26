import { batteryScenarios, maintenancePackagesByAsset } from "./fixtures";
import type { BatteryMode, BatteryScenario, BatteryScenarioRequest, InterventionRequest, MaintenancePackage } from "./types";

const comparableRequestFields: (keyof InterventionRequest)[] = ["duration", "notice", "start", "end", "unavailable", "baseline", "acceptableOutage", "operationalNotes"];

export async function requestMaintenanceRanking(assetId: string, request: InterventionRequest): Promise<MaintenancePackage | null> {
  const materialized = maintenancePackagesByAsset[assetId];
  if (!materialized) return null;
  const matchesMaterializedProfile = comparableRequestFields.every((field) => request[field] === materialized.request[field]);
  const supportedPrice = request.price === null || request.price === materialized.request.price;
  if (!matchesMaterializedProfile || !supportedPrice) return null;
  if (request.price !== null) return { ...materialized, request };
  const windows = materialized.windows.map((window) => ({
    ...window,
    opportunityCost: { ...window.opportunityCost, value: null, unavailableReason: "Preço de cenário não informado" },
    monetaryDifferenceFromBaseline: { ...window.monetaryDifferenceFromBaseline, value: null, unavailableReason: "Preço de cenário não informado" },
  }));
  return { ...materialized, request, windows };
}

const residualByWindow: Record<string, string> = {
  "wind-alt-1": "residual-wind-alt-1",
  "wind-alt-2": "residual-wind-alt-2",
  "wind-base": "residual-wind-base",
  "solar-alt-1": "residual-solar-alt-1",
  "solar-alt-2": "residual-solar-alt-2",
  "solar-base": "residual-solar-base",
};

export function residualProfileForWindow(windowId: string): string | null {
  return residualByWindow[windowId] ?? null;
}

export function requestBatteryScenario(assetId: string, residualProfileId: string, mode: BatteryMode, request?: BatteryScenarioRequest): BatteryScenario | null {
  const scenario = batteryScenarios.find((item) => item.assetId === assetId && item.residualProfileId === residualProfileId && item.mode === mode) ?? null;
  if (!scenario || !request) return scenario;
  const premiseKeys = Object.keys(scenario.request.premises);
  const premisesMatch = premiseKeys.length === Object.keys(request.premises).length && premiseKeys.every((key) => request.premises[key] === scenario.request.premises[key]);
  const textMatches = request.operationalRestrictions === scenario.request.operationalRestrictions && request.meterBoundary === scenario.request.meterBoundary && request.hourlyPriceSource === scenario.request.hourlyPriceSource;
  return premisesMatch && textMatches ? scenario : null;
}

export function defaultResidualProfile(assetId: string): string {
  return assetId === "asset-solar" ? "residual-solar-base" : "residual-wind-base";
}
