import { describe, expect, it } from "vitest";
import { batteryScenario, exposureSummary, maintenanceWindows } from "./fixtures";

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
});
