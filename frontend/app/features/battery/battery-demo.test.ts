import { describe, expect, it } from "vitest";
import { batteryEstimatesByAsset } from "./battery-demo";

const expectedIds = ["RNEM13", "BAEA52", "BAEB0B", "RNMVS2", "PBLZ3"];

describe("estimativas estáticas de bateria", () => {
  it("cobre as cinco usinas com duas análises completas", () => {
    expect(Object.keys(batteryEstimatesByAsset)).toEqual(expectedIds);

    for (const estimate of Object.values(batteryEstimatesByAsset)) {
      expect(estimate.contributionAnalysis).toHaveLength(3);
      expect(estimate.returnAnalysis).toHaveLength(3);
      expect([...estimate.contributionAnalysis, ...estimate.returnAnalysis].join(" ")).not.toMatch(/[—–]/);
    }
  });

  it("mantém os indicadores técnicos coerentes", () => {
    for (const estimate of Object.values(batteryEstimatesByAsset)) {
      expect(estimate.batteryEnergyMwh).toBe(estimate.batteryPowerMw * estimate.dischargeHours);
      const annualDelivery = estimate.batteryEnergyMwh
        * estimate.annualCycles
        * estimate.roundTripEfficiencyPct / 100
        * estimate.availabilityPct / 100;
      expect(estimate.annualDeliveryMwh).toBe(Math.round(annualDelivery));
    }
  });

  it("fecha a composição financeira e o retorno simples", () => {
    for (const estimate of Object.values(batteryEstimatesByAsset)) {
      const grossRevenue = estimate.capacityRevenueMillionBrl
        + estimate.arbitrageRevenueMillionBrl
        + estimate.servicesRevenueMillionBrl;
      expect(estimate.grossRevenueMillionBrl).toBeCloseTo(grossRevenue, 2);
      expect(estimate.netAnnualBenefitMillionBrl).toBeCloseTo(
        estimate.grossRevenueMillionBrl - estimate.annualOpexMillionBrl,
        2,
      );
      const paybackFromDisplayedValues = estimate.capexMillionBrl / estimate.netAnnualBenefitMillionBrl;
      expect(Math.abs(estimate.simplePaybackYears - paybackFromDisplayedValues)).toBeLessThanOrEqual(0.1);
    }
  });
});
