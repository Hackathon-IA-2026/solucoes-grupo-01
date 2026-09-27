import { createContext } from "react";
import type { ExposureAsset, ExposureView } from "~/domain/types";

export type ExposureContextValue = {
  assets: ExposureAsset[];
  selectedAssetId: string | null;
  selectAsset: (assetId: string) => void;
  view: ExposureView | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
};

export const ExposureContext = createContext<ExposureContextValue | null>(null);
