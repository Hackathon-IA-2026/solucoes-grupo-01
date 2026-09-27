import { cleanup, fireEvent, render, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidenceMetadata, ExposureForecastPoint } from "~/domain/types";
import { Forecast60dSlot, ForecastPointTooltip } from "./exposure-charts";

/**
 * recharts needs a measured box, which jsdom never provides. The stub keeps the
 * real chart components and only fixes the responsive size, so the rendered SVG
 * is the production one.
 */
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  const react = await vi.importActual<typeof import("react")>("react");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      react.cloneElement(children as ReactElement<Record<string, unknown>>, { width: 960, height: 320 }),
  };
});

afterEach(cleanup);

const FIRST_DAY = Date.UTC(2026, 8, 26);
const DAY_MS = 86_400_000;

function isoDay(offset: number) {
  return new Date(FIRST_DAY + offset * DAY_MS).toISOString().slice(0, 10);
}

function displayLabel(date: string) {
  const [, month, day] = date.split("-");
  return `${day}/${month}`;
}

const points: ExposureForecastPoint[] = Array.from({ length: 60 }, (_, index) => {
  const date = isoDay(index);
  const expected = 2 + index / 10;
  return {
    forecastDate: date,
    displayLabel: displayLabel(date),
    expectedCurtailedMwh: expected,
    lowerMwh: 1,
    upperMwh: expected + 2,
    curtailmentProbability: 0.25,
    potentialGenerationMwh: 8.5,
    acceptedGenerationEnvelopeMwh: 6.5,
    scheduledMaintenanceReliefMwh: 0.5,
    avoidedCurtailmentMwh: 0.4,
    riskReductionPercentagePoints: 1.5,
  };
});

const evidence: EvidenceMetadata = {
  unit: "MWh/dia",
  period: { start: points[0].forecastDate, end: points[59].forecastDate, label: "horizonte" },
  source: "Teste",
  dataVersion: "teste-v1",
  method: "Fixture de teste",
  state: "simulado",
};

const seriesPoint = {
  label: "12/10",
  date: "2026-10-12",
  expected: 130.5,
  lower: 90,
  upper: 180,
  bandBase: 90,
  bandSpan: 90,
  riskPercent: 82,
};

describe("gráfico em linha da previsão de 60 dias", () => {
  it("mostra data completa, MWh esperados e risco diário no tooltip", () => {
    const { container } = render(<ForecastPointTooltip active payload={[{ payload: seriesPoint }]} />);
    const tooltip = within(container);

    expect(tooltip.getByText("12/10/2026")).toBeInTheDocument();
    expect(tooltip.getByText("130,5 MWh")).toBeInTheDocument();
    expect(tooltip.getByText("82%")).toBeInTheDocument();
    expect(tooltip.getByText(/Energia restringida esperada/)).toBeInTheDocument();
    expect(tooltip.getByText(/Risco de curtailment no dia/)).toBeInTheDocument();
  });

  it("não renderiza tooltip sem dia ativo", () => {
    const { container } = render(<ForecastPointTooltip />);

    expect(container).toBeEmptyDOMElement();
  });

  it("desenha uma linha, não barras, com marcador e label em todos os 60 dias", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);

    expect(container.querySelector('[data-chart-kind="line"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-chart-kind="columns"]')).toHaveLength(0);
    expect(container.querySelectorAll(".recharts-bar")).toHaveLength(0);
    expect(container.querySelector('[data-forecast-point-count="60"]')).not.toBeNull();

    const markers = Array.from(container.querySelectorAll("[data-forecast-marker]"));
    expect(markers).toHaveLength(60);
    expect(markers.map((marker) => marker.getAttribute("data-forecast-date"))).toEqual(points.map((point) => point.forecastDate));
    expect(markers.every((marker) => Number(marker.getAttribute("r")) > 0)).toBe(true);

    const labels = Array.from(container.querySelectorAll("text"))
      .map((node) => node.textContent ?? "")
      .filter((text) => /^\d{2}\/\d{2}$/.test(text));
    expect(labels).toHaveLength(60);
    expect(labels).toEqual(points.map((point) => point.displayLabel));
  });

  it("mantém a faixa de incerteza e o gráfico dentro de uma rolagem horizontal controlada", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);

    const scroll = container.querySelector("[data-chart-scroll]");
    expect(scroll).not.toBeNull();
    expect(scroll?.className).toContain("overflow-x-auto");

    // The uncertainty band is the two stacked areas around the expected line.
    expect(container.querySelectorAll(".recharts-area")).toHaveLength(2);
    expect(container.querySelectorAll(".recharts-line")).toHaveLength(1);
    expect(container.querySelector(".recharts-line-curve")).not.toBeNull();
  });

  it("oferece a tabela equivalente com 60 dias, faixa e risco", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);
    const scope = within(container);

    fireEvent.click(scope.getByRole("button", { name: "Mostrar tabela" }));

    const table = scope.getByRole("table", { name: "Energia restringida estimada por dia e risco de curtailment" });
    expect(within(table).getByRole("columnheader", { name: "MWh esperados" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Risco diário" })).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(61);
    expect(within(table).getByText("26/09/2026")).toBeInTheDocument();
    expect(container.querySelector(".recharts-line")).toBeNull();
  });
});
