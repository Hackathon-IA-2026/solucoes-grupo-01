import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "./chart-frame";

describe("tabela equivalente do gráfico", () => {
  it("nomeia a tabela, identifica os cabeçalhos e não converte ausência em zero", () => {
    render(<DataTable caption="Série de teste" headers={["Período", "Valor"]} rows={[["jan.", null], ["fev.", 0]]} />);
    const table = screen.getByRole("table", { name: "Série de teste" });
    expect(within(table).getByRole("columnheader", { name: "Valor" })).toHaveAttribute("scope", "col");
    expect(within(table).getByText("Indisponível")).toBeInTheDocument();
    expect(within(table).getByText("0")).toBeInTheDocument();
  });
});
