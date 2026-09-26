import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { EvidenceMetric, StateBadge } from "./evidence";
import { EvidenceGuidance } from "./guidance";
import type { EvidenceState } from "~/domain/types";

const states: EvidenceState[] = ["medido", "calculado", "previsto", "simulado", "informado pelo cliente"];

describe("evidência", () => {
  it.each(states)("exibe o estado %s por extenso", (state) => {
    render(<StateBadge state={state} />);
    expect(screen.getByText(state)).toBeInTheDocument();
  });

  it("mostra valor indisponível com motivo e procedência", () => {
    render(<EvidenceMetric label="Preço" evidence={{ value: null, unit: "R$", period: { start: "2026-01-01", end: "2026-01-31", label: "jan. 2026" }, source: "Integração ausente", dataVersion: "demo", method: "Não calculado", state: "simulado", unavailableReason: "Preço não informado" }} />);
    expect(screen.getByText("Indisponível")).toBeInTheDocument();
    expect(screen.getByText("Preço não informado")).toBeInTheDocument();
    expect(screen.getByText("Caminho deste número")).toBeInTheDocument();
  });

  it("renderiza os quatro blocos de orientação", () => {
    render(<MemoryRouter><EvidenceGuidance guidance={{ data: "Dado teste", implication: "Implicação teste", limitation: "Limitação teste", nextAction: "Ação teste", nextHref: "/manutencao" }} /></MemoryRouter>);
    for (const title of ["Dado", "Implicação", "Limitação", "Próxima ação"]) expect(screen.getByText(title)).toBeInTheDocument();
  });
});
