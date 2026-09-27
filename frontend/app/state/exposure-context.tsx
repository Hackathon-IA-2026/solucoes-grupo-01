import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchExposureAssets, fetchExposureView } from "~/domain/exposure-api";
import type { ExposureAsset, ExposureView } from "~/domain/types";
import { ExposureContext, type ExposureContextValue } from "~/state/exposure-context-value";

/**
 * The Exposição selection is intentionally self-contained: it never reads or
 * writes the `AnalysisProvider` state used by the other screens, so choosing a
 * plant here cannot change the analysis asset (and vice versa).
 */
export function ExposureProvider({ children }: { children: ReactNode }) {
  const [assets, setAssets] = useState<ExposureAsset[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [view, setView] = useState<ExposureView | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [viewLoading, setViewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchExposureAssets(controller.signal)
      .then((items) => {
        setAssets(items);
        setViewLoading(true);
        setSelectedAssetId((current) => current && items.some((item) => item.assetId === current) ? current : items[0]?.assetId ?? null);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Não foi possível carregar as usinas.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (!selectedAssetId) return;
    const controller = new AbortController();
    fetchExposureView(selectedAssetId, controller.signal)
      .then((nextView) => {
        if (!controller.signal.aborted) setView(nextView);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setView(null);
          setError(reason instanceof Error ? reason.message : "Não foi possível carregar a análise de Exposição.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setViewLoading(false);
      });
    return () => controller.abort();
  }, [selectedAssetId, revision]);

  const selectAsset = useCallback((assetId: string) => {
    if (!assets.some((asset) => asset.assetId === assetId)) return;
    setViewLoading(true);
    setError(null);
    setSelectedAssetId(assetId);
  }, [assets]);
  const retry = useCallback(() => {
    setViewLoading(true);
    setError(null);
    setRevision((current) => current + 1);
  }, []);
  const value = useMemo<ExposureContextValue>(() => ({
    assets,
    selectedAssetId,
    selectAsset,
    view,
    loading: catalogLoading || viewLoading,
    error,
    retry,
  }), [assets, selectedAssetId, selectAsset, view, catalogLoading, viewLoading, error, retry]);

  return <ExposureContext.Provider value={value}>{children}</ExposureContext.Provider>;
}

