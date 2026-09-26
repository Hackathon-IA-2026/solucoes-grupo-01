import { createContext } from "react";
import type { BatterySelection, DecisionRecord, MaintenancePackage } from "~/domain/types";

export type AnalysisState = { assetId: string; selectionRevision: number; maintenanceAnalysis: MaintenancePackage | null; decision: DecisionRecord | null; batterySelection: BatterySelection | null };
export type AnalysisContextValue = {
  state: AnalysisState;
  selectAsset: (assetId: string) => void;
  recordMaintenanceAnalysis: (analysis: MaintenancePackage | null) => void;
  recordDecision: (decision: DecisionRecord) => void;
  recordBatterySelection: (selection: BatterySelection) => void;
};
export const AnalysisContext = createContext<AnalysisContextValue | null>(null);
