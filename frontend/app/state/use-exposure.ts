import { useContext } from "react";
import { ExposureContext } from "~/state/exposure-context-value";

export function useExposure() {
  const value = useContext(ExposureContext);
  if (!value) throw new Error("useExposure deve ser usado dentro de ExposureProvider");
  return value;
}
