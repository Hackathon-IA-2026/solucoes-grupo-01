import { useContext } from "react";
import { AnalysisContext } from "./analysis-context-value";

export function useAnalysis() {
  const value = useContext(AnalysisContext);
  if (!value) throw new Error("useAnalysis must be used inside AnalysisProvider");
  return value;
}
