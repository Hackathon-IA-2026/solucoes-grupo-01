import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Asset } from "~/domain/types";
import { AssetTopologyBody, type PlantTopologyContext, type PlantTopologyPlant } from "./asset-topology";

const asset: Asset = {
  id: "RNEM13",
  name: "Ventos de Santa Martina 13",
  technology: "Eólica",
  location: "RN",
  connectionPoint: "RNCMM-500-A",
  anonymousEntities: 7,
  telemetry: "simulada",
};

function plant(id: string, name: string): PlantTopologyPlant {
  return { id, name, technology: "wind", groupId: "CJU_RNRDV" };
}

function renderTopology(context?: PlantTopologyContext) {
  const utils = render(<AssetTopologyBody asset={asset} context={context} />);
  const list = utils.container.querySelector<HTMLElement>("[data-topology-list]");
  if (!list) throw new Error("A topologia deve renderizar a visão em lista.");
  const hierarchy = () => Array.from(list.querySelector("ul")!.querySelectorAll("li")).map((item) => item.textContent ?? "");
  const peersOf = (label: string) => {
    const heading = Array.from(list.querySelectorAll("p")).find((item) => item.textContent?.startsWith(label));
    if (!heading?.nextElementSibling) return [];
    return Array.from(heading.nextElementSibling.querySelectorAll("li")).map((item) => item.textContent ?? "");
  };
  return { ...utils, list, hierarchy, peersOf };
}

describe("AssetTopologyBody com contexto de conjunto", () => {
  it("encadeia usina selecionada, conjunto ONS e ponto de conexão na visão em lista", () => {
    const { hierarchy } = renderTopology({
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      groupPlants: [plant("RNEM13", asset.name)],
      pointPlants: [plant("RNEM13", asset.name)],
    });

    const items = hierarchy();
    expect(items).toHaveLength(3);
    expect(items[0]).toContain(asset.name);
    expect(items[1]).toContain("Rio do Vento");
    expect(items[2]).toContain(asset.connectionPoint);
  });

  it("usa o identificador do conjunto quando o nome não é informado e omite o nó de conjunto sem contexto", () => {
    const withId = renderTopology({ onsGroupId: "CJU_RNRDV" });
    expect(withId.hierarchy()[1]).toContain("CJU_RNRDV");

    withId.unmount();
    const withoutContext = renderTopology(undefined);
    const items = withoutContext.hierarchy();
    expect(items[0]).toContain(asset.name);
    expect(items[1]).toContain(asset.connectionPoint);
    expect(withoutContext.list.textContent).not.toContain("Conjunto ao qual a usina pertence");
  });

  it("classifica usinas do mesmo conjunto, do mesmo ponto e de ambos", () => {
    const { peersOf } = renderTopology({
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      groupPlants: [plant("RNEM13", asset.name), plant("GRP1", "Usina Só Conjunto"), plant("BOTH1", "Usina Conjunto e Ponto")],
      pointPlants: [plant("RNEM13", asset.name), plant("PNT1", "Usina Só Ponto"), plant("BOTH1", "Usina Conjunto e Ponto")],
    });

    const reconciliation = peersOf("Reconciliação no conjunto");
    const systemic = peersOf("Pressão sistêmica no ponto");

    expect(reconciliation).toHaveLength(2);
    expect(reconciliation.join(" ")).toContain("Usina Só Conjunto");
    expect(reconciliation.join(" ")).toContain("Mesmo conjunto (reconciliação)");
    expect(reconciliation.join(" ")).toContain("Mesmo conjunto e mesmo ponto");

    expect(systemic).toHaveLength(2);
    expect(systemic.join(" ")).toContain("Usina Só Ponto");
    expect(systemic.join(" ")).toContain("Mesmo ponto (pressão sistêmica)");
    expect(systemic.join(" ")).toContain("Mesmo conjunto e mesmo ponto");
  });

  it("remove a usina selecionada da lista de vizinhas mesmo quando ela vem no contexto", () => {
    const { peersOf, hierarchy, list } = renderTopology({
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      groupPlants: [plant("RNEM13", asset.name), plant("GRP1", "Usina Só Conjunto")],
      pointPlants: [plant("RNEM13", asset.name), plant("PNT1", "Usina Só Ponto")],
    });

    const peers = [...peersOf("Reconciliação no conjunto"), ...peersOf("Pressão sistêmica no ponto")];
    expect(peers.join(" ")).not.toContain(asset.name);
    expect(peers).toHaveLength(2);
    // The selected plant still heads the hierarchy, exactly once.
    expect(hierarchy()[0]).toContain(asset.name);
    expect(list.textContent?.split(asset.name).length).toBe(2);
  });

  it("deduplica identificadores repetidos dentro do mesmo escopo", () => {
    const duplicated = [plant("RNEM13", asset.name), plant("GRP1", "Usina Repetida"), plant("GRP1", "Usina Repetida"), plant("GRP1", "Usina Repetida")];
    const { peersOf, list } = renderTopology({
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      groupPlants: duplicated,
      pointPlants: [plant("RNEM13", asset.name), plant("GRP1", "Usina Repetida")],
    });

    expect(peersOf("Reconciliação no conjunto")).toHaveLength(1);
    expect(peersOf("Pressão sistêmica no ponto")).toHaveLength(1);
    expect(list.textContent).toContain("Reconciliação no conjunto (1)");
    expect(list.textContent).toContain("Pressão sistêmica no ponto (1)");
    expect(list.textContent).toContain("1 usinas únicas somando conjunto e ponto, sem dupla contagem.");
  });

  it("conta a união única entre conjunto e ponto sem dupla contagem", () => {
    const { peersOf, list } = renderTopology({
      onsGroupId: "CJU_RNRDV",
      onsGroupName: "Rio do Vento",
      groupPlants: [
        plant("RNEM13", asset.name),
        plant("GRP1", "Conjunto Um"),
        plant("GRP2", "Conjunto Dois"),
        plant("BOTH1", "Compartilhada"),
      ],
      pointPlants: [
        plant("RNEM13", asset.name),
        plant("PNT1", "Ponto Um"),
        plant("PNT2", "Ponto Dois"),
        plant("PNT3", "Ponto Três"),
        plant("BOTH1", "Compartilhada"),
      ],
    });

    // 3 no conjunto + 4 no ponto, com uma usina em ambos: 3 + 4 - 1 = 6 únicas.
    expect(peersOf("Reconciliação no conjunto")).toHaveLength(3);
    expect(peersOf("Pressão sistêmica no ponto")).toHaveLength(4);
    expect(list.textContent).toContain("Reconciliação no conjunto (3)");
    expect(list.textContent).toContain("Pressão sistêmica no ponto (4)");
    expect(list.textContent).toContain("6 usinas únicas somando conjunto e ponto, sem dupla contagem.");
    expect(list.textContent).not.toContain("7 usinas únicas");
  });

  it("permite alternar entre topologia e lista", () => {
    const { container, list } = renderTopology({ onsGroupId: "CJU_RNRDV", onsGroupName: "Rio do Vento" });
    // Vitest sem `globals` não executa a limpeza automática do Testing Library:
    // as consultas ficam restritas ao container deste render.
    const view = within(container);
    const toggle = view.getByRole("button", { name: "Ver como lista" });

    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(list).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(view.getByRole("button", { name: "Ver topologia" })).toHaveAttribute("aria-pressed", "true");
    expect(list).toHaveClass("block");
  });
});
