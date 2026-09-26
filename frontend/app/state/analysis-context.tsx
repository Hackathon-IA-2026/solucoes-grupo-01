import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getConfiguredCurtaiLessApi } from "~/domain/api-client";
import type { Asset } from "~/domain/types";
import { AnalysisContext, type AnalysisContextValue, type AnalysisState } from "./analysis-context-value";

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AnalysisState>({ assetId: "", selectionRevision: 0, maintenanceAnalysis: null, decision: null, batterySelection: null });
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsStatus, setAssetsStatus] = useState<"loading" | "ready" | "error">("loading");
  const [assetsError, setAssetsError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getConfiguredCurtaiLessApi().listAssets().then((items) => {
      if (!active) return;
      setAssets(items);
      setAssetsStatus("ready");
      setState((current) => current.assetId || !items[0] ? current : { ...current, assetId: items[0].id });
    }).catch((error: unknown) => {
      if (!active) return;
      setAssetsStatus("error");
      setAssetsError(error instanceof Error ? error.message : "Falha ao carregar ativos");
    });
    return () => { active = false; };
  }, []);
  const value = useMemo<AnalysisContextValue>(() => ({
    state, assets, assetsStatus, assetsError,
    selectAsset: (assetId) => setState((current) => ({ assetId, selectionRevision: current.selectionRevision + 1, maintenanceAnalysis: null, decision: null, batterySelection: null })),
    recordMaintenanceAnalysis: (maintenanceAnalysis) => setState((current) => ({ ...current, maintenanceAnalysis, decision: null, batterySelection: null })),
    recordDecision: (decision) => setState((current) => ({ ...current, decision, batterySelection: null })),
    recordBatterySelection: (batterySelection) => setState((current) => ({ ...current, batterySelection })),
  }), [assets, assetsError, assetsStatus, state]);
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}
