import { describe, expect, it } from "vitest";
import { maintenancePackagesByAsset } from "./fixtures";
import { defaultResidualProfile, requestBatteryScenario, requestMaintenanceRanking, residualProfileForWindow } from "./mock-api";

const windRequest = maintenancePackagesByAsset["asset-wind"].request;

describe("API materializada da demonstração", () => {
  it("não reutiliza o ranking quando os parâmetros não correspondem ao pacote", async () => {
    await expect(requestMaintenanceRanking("asset-wind", { ...windRequest, duration: 48 })).resolves.toBeNull();
    await expect(requestMaintenanceRanking("asset-wind", { ...windRequest, price: 450 })).resolves.toBeNull();
  });

  it("mantém ranking energético quando o preço não é informado", async () => {
    const response = await requestMaintenanceRanking("asset-wind", { ...windRequest, price: null });
    expect(response?.request.price).toBeNull();
    expect(response?.windows[0].interventionLoss.value).toBe(18.4);
    expect(response?.windows[0].opportunityCost.value).toBeNull();
    expect(response?.windows[0].monetaryDifferenceFromBaseline.value).toBeNull();
  });

  it("vincula cada janela a um perfil residual e a um cenário BESS distinto", () => {
    const alternativeResidual = residualProfileForWindow("wind-alt-1");
    const baselineResidual = residualProfileForWindow("wind-base");
    expect(alternativeResidual).not.toBe(baselineResidual);
    const alternative = requestBatteryScenario("asset-wind", alternativeResidual!, "new");
    const baseline = requestBatteryScenario("asset-wind", baselineResidual!, "new");
    expect(alternative?.residualEnergy.value).not.toBe(baseline?.residualEnergy.value);
  });

  it("recusa parâmetros BESS alterados em vez de recalcular no cliente", () => {
    const template = requestBatteryScenario("asset-wind", "residual-wind-base", "existing");
    expect(template).not.toBeNull();
    expect(requestBatteryScenario("asset-wind", "residual-wind-base", "existing", template!.request)?.id).toBe(template?.id);
    expect(requestBatteryScenario("asset-wind", "residual-wind-base", "existing", { ...template!.request, premises: { ...template!.request.premises, capacity: 81 } })).toBeNull();
  });

  it("mantém os pacotes dos ativos separados", () => {
    expect(defaultResidualProfile("asset-wind")).not.toBe(defaultResidualProfile("asset-solar"));
    expect(requestBatteryScenario("asset-wind", "residual-solar-base", "new")).toBeNull();
  });
});
