import { useMemo, useState, type ReactNode } from "react";
import { AnalysisContext, type AnalysisContextValue, type AnalysisState } from "./analysis-context-value";

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AnalysisState>({ assetId: "asset-wind", selectionRevision: 0, maintenanceAnalysis: null, decision: null, batterySelection: null });
  const value = useMemo<AnalysisContextValue>(() => ({
    state,
    selectAsset: (assetId) => setState((current) => ({ assetId, selectionRevision: current.selectionRevision + 1, maintenanceAnalysis: null, decision: null, batterySelection: null })),
    recordMaintenanceAnalysis: (maintenanceAnalysis) => setState((current) => ({ ...current, maintenanceAnalysis, decision: null, batterySelection: null })),
    recordDecision: (decision) => setState((current) => ({ ...current, decision, batterySelection: null })),
    recordBatterySelection: (batterySelection) => setState((current) => ({ ...current, batterySelection })),
  }), [state]);
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}
