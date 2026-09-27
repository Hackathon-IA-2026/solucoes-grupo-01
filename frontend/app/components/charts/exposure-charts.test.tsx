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
  potential: 130.5,
  operationalLimit: 90,
};

describe("gráfico em linha da previsão de 60 dias", () => {
  it("mostra data, geração potencial e limite operacional no tooltip", () => {
    const { container } = render(<ForecastPointTooltip active payload={[{ payload: seriesPoint }]} />);
    const tooltip = within(container);

    expect(tooltip.getByText("12/10/2026")).toBeInTheDocument();
    expect(tooltip.getByText("130,5 MWh")).toBeInTheDocument();
    expect(tooltip.getByText("90 MWh")).toBeInTheDocument();
    expect(tooltip.getByText(/Geração potencial/)).toBeInTheDocument();
    expect(tooltip.getByText(/Limite operacional/)).toBeInTheDocument();
  });

  it("não renderiza tooltip sem dia ativo", () => {
    const { container } = render(<ForecastPointTooltip />);

    expect(container).toBeEmptyDOMElement();
  });

  it("desenha duas linhas e mostra somente uma data por semana", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);

    expect(container.querySelector('[data-chart-kind="line"]')).not.toBeNull();
    expect(container.querySelector('[data-chart-lines="2"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-chart-kind="columns"]')).toHaveLength(0);
    expect(container.querySelectorAll(".recharts-bar")).toHaveLength(0);
    expect(container.querySelector('[data-forecast-point-count="60"]')).not.toBeNull();

    const labels = Array.from(container.querySelectorAll("text"))
      .map((node) => node.textContent ?? "")
      .filter((text) => /^\d{2}\/\d{2}$/.test(text));
    expect(labels.length).toBeGreaterThanOrEqual(8);
    expect(labels.length).toBeLessThanOrEqual(9);
    expect(labels[0]).toBe(points[0].displayLabel);
  });

  it("remove a faixa de incerteza e a rolagem horizontal", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);

    expect(container.querySelector("[data-chart-scroll]")).toBeNull();
    expect(container.querySelectorAll(".recharts-area")).toHaveLength(0);
    expect(container.querySelectorAll(".recharts-line")).toHaveLength(2);
  });

  it("oferece a tabela equivalente com potencial e limite operacional", () => {
    const { container } = render(<Forecast60dSlot points={points} description="Descrição" evidence={evidence} />);
    const scope = within(container);

    fireEvent.click(scope.getByRole("button", { name: "Mostrar tabela" }));

    const table = scope.getByRole("table", { name: "Geração potencial e limite operacional por dia" });
    expect(within(table).getAllByRole("row")).toHaveLength(61);
    expect(within(table).getByRole("columnheader", { name: "Geração potencial (MWh)" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Limite operacional (MWh)" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Risco diário" })).not.toBeInTheDocument();
    expect(within(table).getAllByText("01/10/2026").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("20/11/2026").length).toBeGreaterThan(0);
  });
});
