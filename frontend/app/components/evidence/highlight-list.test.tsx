import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HighlightList, MetricComposition } from "./highlight-list";

describe("HighlightList", () => {
  it("apresenta informações como uma lista sem controles ou cards internos", () => {
    const { container } = render(
      <HighlightList
        label="Leitura da exposição"
        items={[
          { label: "Informação principal", value: "42%", detail: "Explicação curta para o cliente." },
          { label: "Segunda informação", value: "8 dias" },
        ]}
      />,
    );

    const list = screen.getByLabelText("Leitura da exposição");
    expect(within(list).getByText("Informação principal")).toBeInTheDocument();
    expect(within(list).getByText("42%")).toBeInTheDocument();
    expect(within(list).getByText("Explicação curta para o cliente.")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-highlight-row]")).toHaveLength(2);
    expect(container.querySelector("article")).not.toBeInTheDocument();
    expect(container.querySelector("details")).not.toBeInTheDocument();
    expect(container.querySelector("button")).not.toBeInTheDocument();
  });

  it("aplica hierarquia sem depender do valor recebido", () => {
    const { container } = render(
      <HighlightList
        label="Indicadores variáveis"
        variant="metrics"
        items={[
          { label: "Indicador principal", value: "18,7", unit: "GWh", emphasis: "hero" },
          { label: "Janela dinâmica", value: "71", unit: "%", detail: "Descrição retornada pelo backend.", emphasis: "primary" },
        ]}
      />,
    );

    expect(container.querySelector('[data-highlight-row][data-emphasis="hero"]')).toHaveTextContent("18,7 GWh");
    expect(container.querySelector('[data-highlight-row][data-emphasis="primary"]')).toHaveAttribute("data-layout", "stacked");
    expect(container.querySelector('[data-highlight-row][data-emphasis="primary"]')).toHaveTextContent("Descrição retornada pelo backend.");
  });
});

describe("MetricComposition", () => {
  it("representa uma composição com valores e segmentos derivados dos dados", () => {
    const { container } = render(
      <MetricComposition
        label="Abrangência dos registros"
        items={[
          { label: "Compartilhados", value: 73, displayValue: "73%" },
          { label: "Somente nesta usina", value: 27, displayValue: "27%" },
        ]}
      />,
    );

    expect(screen.getByLabelText("Abrangência dos registros")).toBeInTheDocument();
    expect(screen.getByText("73%")).toBeInTheDocument();
    expect(screen.getByText("27%")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-composition-segment]")).toHaveLength(2);
  });
});
