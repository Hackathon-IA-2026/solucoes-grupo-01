import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EnergyNetworkIllustration } from "./energy-network-illustration";
import { getConnectedPlantSlots, getNetworkConnectionPath } from "./network-layout";

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
    [3, 3],
    [6, 6],
    [8, 8],
    [12, 8],
  ])("renderiza %i conexões como %i usinas menores", (connectedCount, expectedCount) => {
    const { container } = render(
      <EnergyNetworkIllustration technology="Eólica" sectionId="secao-ativo" connectedCount={connectedCount} />,
    );

    expect(container.querySelectorAll("[data-connected-plant]")).toHaveLength(expectedCount);
    expect(container.querySelectorAll("[data-network-connection]")).toHaveLength(expectedCount + 1);
  });

  it("mantém as seis primeiras usinas inteiras e reserva cortes somente para sete e oito", () => {
    const slots = getConnectedPlantSlots(8);

    for (const slot of slots.slice(0, 6)) {
      expect(slot.edge).not.toBe(true);
      expect(slot.x - 120 * slot.scale).toBeGreaterThanOrEqual(0);
      expect(slot.x + 120 * slot.scale).toBeLessThanOrEqual(600);
      expect(slot.y - 120 * slot.scale).toBeGreaterThanOrEqual(0);
      expect(slot.y + 246 * slot.scale).toBeLessThanOrEqual(900);
    }
    expect(slots.slice(6)).toEqual(expect.arrayContaining([
      expect.objectContaining({ edge: true }),
      expect.objectContaining({ edge: true }),
    ]));
  });

  it("conecta cada usina com um joelho ortogonal no plano isométrico", () => {
    const isometricSlope = 1 / Math.sqrt(3);

    for (const slot of getConnectedPlantSlots(8)) {
      const coordinates = getNetworkConnectionPath(slot).match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
      const [startX, startY, elbowX, elbowY, endX, endY] = coordinates;
      const firstSlope = Math.abs((elbowY - startY) / (elbowX - startX));
      const secondSlope = Math.abs((endY - elbowY) / (endX - elbowX));
      expect(firstSlope).toBeCloseTo(isometricSlope, 2);
      expect(secondSlope).toBeCloseTo(isometricSlope, 2);
    }
  });

  it("mantém a animação incorporada sem controles visíveis", () => {
    const { container } = render(
      <EnergyNetworkIllustration technology="Solar" sectionId="secao-ativo" connectedCount={3} />,
    );

    expect(container.querySelector("button")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-connected-plant]")).toHaveLength(3);
    expect(container.querySelectorAll('animate[attributeName="stroke-dashoffset"]')).toHaveLength(4);
    expect(container.querySelectorAll("animateTransform")).toHaveLength(12);
  });
});
