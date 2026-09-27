import { fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { ExposureAsset } from "~/domain/types";
import { AnalysisContext, type AnalysisContextValue } from "~/state/analysis-context-value";
import { ExposureContext, type ExposureContextValue } from "~/state/exposure-context-value";
import { AssetPicker } from "./asset-picker";

function exposureAsset(overrides: Partial<ExposureAsset> & Pick<ExposureAsset, "assetId" | "name">): ExposureAsset {
  return {
    entityLevel: "plant",
    technology: "wind",
    state: "RN",
    connectionPoint: "RNPONTO-500-A",
    capacityMw: 50,
    connectedAssetCount: 4,
    operationalDataStatus: "simulated",
    allocationCoverage: null,
    onsGroupId: null,
    onsGroupName: null,
    ceg: null,
    ...overrides,
  };
}

function renderPicker({
  assets,
  selectedAssetId = null,
  path = "/exposicao",
}: {
  assets: ExposureAsset[];
  selectedAssetId?: string | null;
  path?: string;
}) {
  const selectExposureAsset = vi.fn();
  const selectAnalysisAsset = vi.fn();
  const exposure: ExposureContextValue = {
    assets,
    selectedAssetId,
    selectAsset: selectExposureAsset,
    view: null,
    loading: false,
    error: null,
    retry: vi.fn(),
  };
  const analysis: AnalysisContextValue = {
    state: { assetId: "asset-wind", selectionRevision: 0, maintenanceAnalysis: null, decision: null, batterySelection: null },
    selectAsset: selectAnalysisAsset,
    recordMaintenanceAnalysis: vi.fn(),
    recordDecision: vi.fn(),
    recordBatterySelection: vi.fn(),
  };

  const utils = render(
    <MemoryRouter initialEntries={[path]}>
      <AnalysisContext.Provider value={analysis}>
        <ExposureContext.Provider value={exposure}>
          <AssetPicker />
        </ExposureContext.Provider>
      </AnalysisContext.Provider>
    </MemoryRouter>,
  );

  // jsdom does not implement showModal/close, but the dialog content is always in the DOM.
  const dialog = utils.container.querySelector("dialog");
  if (!dialog) throw new Error("O seletor de usina deve renderizar um <dialog>.");
  const options = () => Array.from(dialog.querySelectorAll("li > button"));
  const optionNames = () => options().map((option) => option.querySelector("span > span")?.textContent ?? "");
  const optionDetails = () => options().map((option) => option.querySelectorAll("span > span")[1]?.textContent ?? "");

  return { ...utils, dialog, options, optionNames, optionDetails, selectExposureAsset, selectAnalysisAsset };
}

/**
 * Two generation-group entries (`CJU_*`) sit before the plants on purpose: a
 * slice-before-filter regression would return fewer than five plant options.
 */
const exposureCatalogue: ExposureAsset[] = [
  exposureAsset({ assetId: "CJU_RNRDV", name: "CJU_RNRDV" }),
  exposureAsset({ assetId: "CJU_RNMVS", name: "Conjunto Monte Verde" }),
  exposureAsset({ assetId: "RNEM13", name: "Ventos de Santa Martina 13", onsGroupId: "CJU_RNRDV", onsGroupName: "Rio do Vento" }),
  exposureAsset({ assetId: "RNMVS2", name: "Monte Verde Solar II", technology: "solar", onsGroupId: "CJU_RNMVS", onsGroupName: "Monte Verde Solar" }),
  exposureAsset({ assetId: "RNP3", name: "Usina P3" }),
  exposureAsset({ assetId: "RNP4", name: "Usina P4" }),
  exposureAsset({ assetId: "RNP5", name: "Usina P5" }),
  exposureAsset({ assetId: "RNP6", name: "Usina P6" }),
  exposureAsset({ assetId: "RNP7", name: "Usina P7" }),
];

describe("AssetPicker na Exposição", () => {
  it("filtra identificadores de conjunto CJU_* e limita a cinco usinas", () => {
    const { optionNames, dialog } = renderPicker({ assets: exposureCatalogue });

    const names = optionNames();
    expect(names).toHaveLength(5);
    expect(names).toEqual(["Ventos de Santa Martina 13", "Monte Verde Solar II", "Usina P3", "Usina P4", "Usina P5"]);
    expect(names.some((name) => name.startsWith("CJU_"))).toBe(false);
    expect(dialog.textContent).not.toContain("Conjunto Monte Verde");
    // Plants beyond the fifth option are not offered.
    expect(names).not.toContain("Usina P6");
    expect(names).not.toContain("Usina P7");
  });

  it("mostra nome da usina, tecnologia, estado e conjunto ONS de cada opção", () => {
    const { optionNames, optionDetails } = renderPicker({
      assets: [
        exposureAsset({ assetId: "RNEM13", name: "Ventos de Santa Martina 13", technology: "wind", state: "RN", onsGroupId: "CJU_RNRDV", onsGroupName: "Rio do Vento" }),
        exposureAsset({ assetId: "MGPV1", name: "Usina Solar MG", technology: "solar", state: "MG", onsGroupId: "CJU_MGPV" }),
        exposureAsset({ assetId: "BAPV2", name: "Usina Solar BA", technology: "solar", state: "BA" }),
      ],
    });

    expect(optionNames()).toEqual(["Ventos de Santa Martina 13", "Usina Solar MG", "Usina Solar BA"]);
    expect(optionDetails()).toEqual([
      "Eólica | RN | Rio do Vento",
      "Solar | MG | CJU_MGPV",
      "Solar | BA | Conjunto ONS não informado",
    ]);
  });

  it("usa a usina selecionada como rótulo do seletor", () => {
    const { container } = renderPicker({ assets: exposureCatalogue, selectedAssetId: "RNMVS2" });

    expect(container.querySelector("[data-asset-picker]")).toHaveTextContent("Monte Verde Solar II");
  });

  it("seleciona pelo contexto de Exposição sem tocar no AnalysisProvider", () => {
    const { options, selectExposureAsset, selectAnalysisAsset } = renderPicker({
      assets: exposureCatalogue,
      selectedAssetId: "RNEM13",
    });

    fireEvent.click(options()[1]);

    expect(selectExposureAsset).toHaveBeenCalledTimes(1);
    expect(selectExposureAsset).toHaveBeenCalledWith("RNMVS2");
    expect(selectAnalysisAsset).not.toHaveBeenCalled();
  });

  it("não reseleciona a usina já ativa", () => {
    const { options, selectExposureAsset, selectAnalysisAsset } = renderPicker({
      assets: exposureCatalogue,
      selectedAssetId: "RNEM13",
    });

    expect(options()[0]).toHaveAttribute("aria-current", "true");
    fireEvent.click(options()[0]);

    expect(selectExposureAsset).not.toHaveBeenCalled();
    expect(selectAnalysisAsset).not.toHaveBeenCalled();
  });

  it.each(["/manutencao", "/bateria"])("mantém as cinco usinas individuais em %s", (path) => {
    const { optionNames, options, selectExposureAsset, selectAnalysisAsset } = renderPicker({
      assets: exposureCatalogue,
      selectedAssetId: "RNEM13",
      path,
    });

    expect(optionNames()).toEqual(["Ventos de Santa Martina 13", "Monte Verde Solar II", "Usina P3", "Usina P4", "Usina P5"]);
    fireEvent.click(options()[1]);

    expect(selectExposureAsset).toHaveBeenCalledWith("RNMVS2");
    expect(selectAnalysisAsset).not.toHaveBeenCalled();
  });

  it("mantém o catálogo de demonstração e o AnalysisProvider fora das três análises", () => {
    const { optionNames, options, selectExposureAsset, selectAnalysisAsset } = renderPicker({
      assets: exposureCatalogue,
      path: "/relatorio",
    });

    expect(optionNames()).toEqual(["Ativo Eólico RN-01", "Ativo Solar MG-02"]);
    fireEvent.click(options()[1]);

    expect(selectAnalysisAsset).toHaveBeenCalledWith("asset-solar");
    expect(selectExposureAsset).not.toHaveBeenCalled();
  });
});
