import { describe, expect, it } from "vitest";
import { assetExposureById, batteryScenario, exposureSummary, forecastWindowsByAsset, maintenanceWindows } from "./fixtures";

const required = ["value", "unit", "period", "source", "dataVersion", "method", "state"];

describe("contratos da demonstração", () => {
  it("mantém procedência completa nos indicadores principais", () => {
    const values = [exposureSummary.total, exposureSummary.characterized, batteryScenario.residualEnergy, ...maintenanceWindows.flatMap((window) => [window.expectedCurtailment, window.interventionLoss, window.opportunityCost, window.differenceFromBaseline, window.coverage])];
    for (const value of values) for (const key of required) expect(value).toHaveProperty(key);
  });

  it("mantém uma janela-base e uma janela inelegível auditável", () => {
    expect(maintenanceWindows.filter((window) => window.baseline)).toHaveLength(1);
    expect(maintenanceWindows.some((window) => !window.eligible && window.eligibilityReason.length > 0)).toBe(true);
  });

  it("não classifica despacho BESS como previsto", () => {
    expect(batteryScenario.absorbableEnergy.state).toBe("calculado");
    expect(batteryScenario.missingInputs).toContain("Estado de carga cronológico");
  });

  it("mantém a previsão demonstrativa separada e com horizonte de 60 dias", () => {
    for (const [assetId, exposure] of Object.entries(assetExposureById)) {
      const start = new Date(`${exposure.forecast60d.evidence.period.start}T00:00:00Z`);
      const end = new Date(`${exposure.forecast60d.evidence.period.end}T00:00:00Z`);
      expect((end.getTime() - start.getTime()) / 86_400_000 + 1).toBe(60);
      expect(exposure.forecast60d.evidence.state).toBe("simulado");
      expect(exposure.forecast60d.points.length).toBeGreaterThan(0);
      expect(forecastWindowsByAsset[assetId as keyof typeof forecastWindowsByAsset].length).toBeGreaterThan(0);
    }
  });
});
