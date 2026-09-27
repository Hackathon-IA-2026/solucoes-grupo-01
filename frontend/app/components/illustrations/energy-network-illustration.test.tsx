import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EnergyNetworkIllustration } from "./energy-network-illustration";
import {
  MAIN_NETWORK_CONNECTION,
  SOLAR_MAIN_NETWORK_CONNECTION,
  getConnectedPlantSlots,
  getNetworkConnectionPath,
} from "./network-layout";

const sectionIds = ["secao-ativo", "secao-resumo"];

describe("EnergyNetworkIllustration", () => {
  it("seleciona a ilustração pela tecnologia e mantém cada instância identificável", () => {
    const { container, rerender } = render(
      <>{sectionIds.map((sectionId) => <EnergyNetworkIllustration key={sectionId} technology="Eólica" sectionId={sectionId} connectedCount={5} />)}</>,
    );

    const windIllustrations = container.querySelectorAll('[data-energy-illustration="wind"]');
    expect(windIllustrations).toHaveLength(2);
    expect(windIllustrations[0]).toHaveAttribute("data-illustration-section", "secao-ativo");
    expect(new Set([...container.querySelectorAll("svg[role=img]")].map((svg) => svg.getAttribute("aria-labelledby"))).size).toBe(2);

    rerender(<EnergyNetworkIllustration technology="Solar" sectionId="secao-previsao" connectedCount={3} />);
    expect(container.querySelector('[data-energy-illustration="solar"]')).toHaveAttribute("data-illustration-section", "secao-previsao");
    expect(container.querySelector('[data-energy-illustration="wind"]')).not.toBeInTheDocument();
  });

  it.each([
    [0, 0],
    [1, 1],
    [3, 3],
    [8, 3],
    [66, 3],
  ])("representa %i conexões com %i símbolos e um contador", (connectedCount, expectedCount) => {
    const { container } = render(
      <EnergyNetworkIllustration technology="Eólica" sectionId="secao-ativo" connectedCount={connectedCount} />,
    );

    expect(container.querySelectorAll("[data-connected-plant]")).toHaveLength(expectedCount);
    expect(container.querySelectorAll("[data-network-connection]")).toHaveLength(expectedCount + 2);
    expect(container.querySelector("[data-connected-count]")).toHaveAttribute("data-connected-count", String(connectedCount));
  });

  it("mantém os três símbolos à direita dentro da composição", () => {
    const slots = getConnectedPlantSlots(66);

    expect(slots).toHaveLength(3);
    for (const slot of slots) {
      expect(slot.x).toBeGreaterThan(800);
      expect(slot.x + 150 * slot.scale).toBeLessThanOrEqual(1200);
      expect(slot.y - 120 * slot.scale).toBeGreaterThanOrEqual(0);
      expect(slot.y + 246 * slot.scale).toBeLessThanOrEqual(900);
    }
  });

  it("conecta o contador aos símbolos com joelhos isométricos de 90 graus", () => {
    const isometricSlope = 1 / Math.sqrt(3);

    for (const slot of getConnectedPlantSlots(66)) {
      const path = getNetworkConnectionPath(slot);
      const coordinates = path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
      const [startX, startY, elbowX, elbowY, endX, endY] = coordinates;
      const firstSlope = (elbowY - startY) / (elbowX - startX);
      const secondSlope = (endY - elbowY) / (endX - elbowX);

      expect(path).toMatch(/^M [-\d.]+ [-\d.]+ L [-\d.]+ [-\d.]+ L [-\d.]+ [-\d.]+$/);
      expect(Math.abs(firstSlope)).toBeCloseTo(isometricSlope, 2);
      expect(Math.abs(secondSlope)).toBeCloseTo(isometricSlope, 2);
      expect(firstSlope * secondSlope).toBeLessThan(0);
    }
  });

  it("liga a rede às usinas principais nos eixos isométricos, sem curvas Bézier", () => {
    const isometricSlope = 1 / Math.sqrt(3);

    for (const path of [MAIN_NETWORK_CONNECTION, SOLAR_MAIN_NETWORK_CONNECTION]) {
      const coordinates = path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
      const [startX, startY, firstX, firstY, secondX, secondY, endX, endY] = coordinates;

      expect(path).toMatch(/^M [-\d.]+ [-\d.]+ L [-\d.]+ [-\d.]+ L [-\d.]+ [-\d.]+ L [-\d.]+ [-\d.]+$/);
      expect(path).not.toContain(" C ");
      expect(Math.abs((firstY - startY) / (firstX - startX))).toBeCloseTo(isometricSlope, 2);
      expect(secondX).toBe(firstX);
      expect(Math.abs((endY - secondY) / (endX - secondX))).toBeCloseTo(isometricSlope, 2);
    }
  });

  it("mantém a animação incorporada sem controles visíveis", () => {
    const { container } = render(
      <EnergyNetworkIllustration technology="Solar" sectionId="secao-ativo" connectedCount={3} />,
    );

    expect(container.querySelector("button")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-connected-plant]")).toHaveLength(3);
    expect(container.querySelectorAll('animate[attributeName="stroke-dashoffset"]')).toHaveLength(5);
    expect(container.querySelectorAll("animateTransform")).toHaveLength(12);
  });
});
