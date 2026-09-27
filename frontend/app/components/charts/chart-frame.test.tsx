import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EvidenceMetadata } from "~/domain/types";
import { ChartBody, DataTable } from "./chart-frame";

const evidence: EvidenceMetadata = {
  unit: "%",
  period: { start: "2026-01-01", end: "2026-01-31", label: "jan. 2026" },
  source: "Teste",
  dataVersion: "teste-v1",
  method: "Fixture de teste",
  state: "simulado",
};

describe("tabela equivalente do gráfico", () => {
  it("nomeia a tabela, identifica os cabeçalhos e não converte ausência em zero", () => {
    render(<DataTable caption="Série de teste" headers={["Período", "Valor"]} rows={[["jan.", null], ["fev.", 0]]} />);
    const table = screen.getByRole("table", { name: "Série de teste" });
    expect(within(table).getByRole("columnheader", { name: "Valor" })).toHaveAttribute("scope", "col");
    expect(within(table).getByText("Indisponível")).toBeInTheDocument();
    expect(within(table).getByText("0")).toBeInTheDocument();
  });

  it("troca o gráfico pela tabela no mesmo componente", () => {
    render(<ChartBody evidence={evidence} table={<div data-testid="table-view">Tabela</div>} showProvenance={false} switchView><div data-testid="chart-view">Gráfico</div></ChartBody>);

    expect(screen.getByTestId("chart-view")).toBeInTheDocument();
    expect(screen.queryByTestId("table-view")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mostrar tabela" }));

    expect(screen.queryByTestId("chart-view")).not.toBeInTheDocument();
    expect(screen.getByTestId("table-view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mostrar gráfico" })).toBeInTheDocument();
  });

  it("exibe somente o gráfico quando não existe visualização tabular", () => {
    render(<ChartBody evidence={evidence} showProvenance={false}><div data-testid="chart-only">Gráfico</div></ChartBody>);

    expect(screen.getByTestId("chart-only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mostrar tabela" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ver dados em tabela")).not.toBeInTheDocument();
  });
});
