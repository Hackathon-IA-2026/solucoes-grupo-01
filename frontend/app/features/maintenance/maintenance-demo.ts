import type { MaintenanceWindow } from "~/domain/types";

export type MaintenanceSuggestion = {
  id: string;
  rank: number;
  start: string;
  end: string;
  durationHours: number;
  avoidedLossMwh: number;
  scenarioPricePerMwh: number;
  reason: string;
};

export type PlantMaintenanceBooking = {
  start: string;
  durationHours: number;
  observations: string;
  suggestionId: string | null;
};

export type MaintenanceReductionPoint = {
  date: string;
  label: string;
  curtailmentBeforeMwh: number;
  scheduledReductionMwh: number;
  plantReductionMwh: number;
  residualCurtailmentMwh: number;
  curtailmentProbability: number;
};

export const SCENARIO_REFERENCE_DATE = "2026-09-25T00:00:00Z";
export const SCENARIO_START_DATE = "2026-10-01";
export const SCENARIO_DAYS = 31;

const OTHER_PLANT_MAINTENANCE_DAYS = new Map<number, number>([
  [5, 31.4],
  [6, 18.7],
  [14, 26.8],
  [15, 34.2],
  [19, 22.5],
  [20, 29.6],
  [23, 37.1],
  [24, 16.9],
]);

export const scheduledPlantSummaries = [
  { plant: "Usina conectada 02", period: "6 a 7 de outubro", reductionMwh: 50.1 },
  { plant: "Usina conectada 04", period: "15 a 16 de outubro", reductionMwh: 61.0 },
  { plant: "Usina conectada 07", period: "20 a 21 de outubro", reductionMwh: 52.1 },
  { plant: "Usina conectada 09", period: "24 a 25 de outubro", reductionMwh: 54.0 },
];

export function suggestionsFromWindows(windows: MaintenanceWindow[], scenarioPricePerMwh: number): MaintenanceSuggestion[] {
  return windows
    .filter((window) => window.eligible)
    .sort((left, right) => left.rank - right.rank)
    .slice(0, 3)
    .map((window) => ({
      id: window.id,
      rank: window.rank,
      start: window.start,
      end: window.end,
      durationHours: window.duration.value ?? 24,
      avoidedLossMwh: window.expectedCurtailment.value ?? 0,
      scenarioPricePerMwh,
      reason: window.baseline
        ? "Mantém a referência informada para o cenário."
        : "Concentra a intervenção em um período com curtailment previsto.",
    }));
}

export function estimatedDailyGeneration(technology: "Eólica" | "Solar") {
  return technology === "Solar" ? 31.6 : 38.4;
}

export function buildMaintenanceReductionSeries(
  booking: PlantMaintenanceBooking | null,
  plantDailyGenerationMwh: number,
): MaintenanceReductionPoint[] {
  const firstDay = Date.parse(`${SCENARIO_START_DATE}T00:00:00Z`);
  const bookingStart = booking ? Date.parse(booking.start) : null;
  const bookingEnd = bookingStart === null || !booking
    ? null
    : bookingStart + booking.durationHours * 3_600_000;

  return Array.from({ length: SCENARIO_DAYS }, (_, index) => {
    const dayStart = firstDay + index * 86_400_000;
    const dayEnd = dayStart + 86_400_000;
    const date = new Date(dayStart).toISOString().slice(0, 10);
    const curtailmentBeforeMwh = 118 + (index % 7) * 8.4 + (index % 3) * 4.7;
    const scheduledReductionMwh = Math.min(OTHER_PLANT_MAINTENANCE_DAYS.get(index) ?? 0, curtailmentBeforeMwh);
    const overlapStart = bookingStart === null ? 0 : Math.max(dayStart, bookingStart);
    const overlapEnd = bookingEnd === null ? 0 : Math.min(dayEnd, bookingEnd);
    const overlapHours = Math.max(0, overlapEnd - overlapStart) / 3_600_000;
    const residualAfterOthers = curtailmentBeforeMwh - scheduledReductionMwh;
    const plantReductionMwh = Math.min(residualAfterOthers, plantDailyGenerationMwh * overlapHours / 24);
    const residualCurtailmentMwh = Math.max(0, residualAfterOthers - plantReductionMwh);

    return {
      date,
      label: `${date.slice(8, 10)}/${date.slice(5, 7)}`,
      curtailmentBeforeMwh,
      scheduledReductionMwh,
      plantReductionMwh,
      residualCurtailmentMwh,
      curtailmentProbability: Math.min(0.86, 0.56 + (index % 6) * 0.055),
    };
  });
}
