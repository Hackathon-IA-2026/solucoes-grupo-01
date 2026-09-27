import { useRef } from "react";
import { BuildingsIcon, CheckCircleIcon, XIcon } from "@phosphor-icons/react";
import { useLocation } from "react-router";
import { assets as demonstrationAssets } from "~/domain/fixtures";
import { cn } from "~/lib/cn";
import { useAnalysis } from "~/state/use-analysis";
import { useExposure } from "~/state/use-exposure";

type PickerAsset = { id: string; name: string; detail: string };

export function AssetPicker() {
  const analysis = useAnalysis();
  const exposure = useExposure();
  const location = useLocation();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const exposureMode = location.pathname === "/exposicao";
  const assets: PickerAsset[] = exposureMode
    ? exposure.assets.map((asset) => ({
        id: asset.assetId,
        name: asset.name,
        detail: `Conjunto ONS | ${asset.technology === "wind" ? "Eólica" : "Solar"} | ${asset.state}`,
      }))
    : demonstrationAssets.map((asset) => ({
        id: asset.id,
        name: asset.name,
        detail: `${asset.technology} | ${asset.location} | Telemetria ${asset.telemetry}`,
      }));
  const selectedId = exposureMode ? exposure.selectedAssetId : analysis.state.assetId;
  const activeAsset = assets.find((asset) => asset.id === selectedId) ?? assets[0];
  const open = () => {
    const dialog = dialogRef.current;
    if (typeof dialog?.showModal === "function") dialog.showModal();
  };
  const close = () => {
    const dialog = dialogRef.current;
    if (typeof dialog?.close === "function") dialog.close();
  };
  const choose = (assetId: string) => {
    if (assetId !== selectedId) {
      if (exposureMode) exposure.selectAsset(assetId);
      else analysis.selectAsset(assetId);
    }
    close();
  };
  return (
    <>
      <button
        type="button"
        onClick={open}
        aria-haspopup="dialog"
        data-asset-picker=""
        className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border border-line bg-white text-sm font-semibold text-ink hover:border-accent hover:bg-accent-soft max-sm:size-11 sm:px-3"
      >
        <BuildingsIcon aria-hidden="true" />
        <span className="sr-only">Selecionar conjunto gerador</span>
        <span className="max-w-[18ch] truncate max-sm:hidden">{activeAsset?.name ?? "Carregando conjuntos"}</span>
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby="asset-picker-title"
        className="m-auto w-[min(92vw,34rem)] rounded-xl border border-line bg-surface p-0 text-ink shadow-[0_12px_32px_rgba(16,42,42,.22)] backdrop:bg-ink/40"
        onClick={(event) => { if (event.target === dialogRef.current) close(); }}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line p-4 sm:p-5">
          <div>
            <h2 id="asset-picker-title" className="text-lg font-semibold">Conjunto gerador em análise</h2>
            <p className="mt-1 text-sm leading-6 text-ink-soft">Os dados públicos de restrição do Operador Nacional do Sistema Elétrico são publicados neste nível agregado. Cada opção pode reunir várias usinas individuais.</p>
          </div>
          <button type="button" onClick={close} aria-label="Fechar seleção de conjunto gerador" className="grid size-11 shrink-0 place-items-center rounded-lg text-ink-soft hover:bg-accent-soft hover:text-ink">
            <XIcon aria-hidden="true" />
          </button>
        </div>
        <ul className="space-y-2 p-4 sm:p-5">
          {assets.map((asset) => {
            const selected = asset.id === selectedId;
            return (
              <li key={asset.id}>
                <button
                  type="button"
                  onClick={() => choose(asset.id)}
                  aria-current={selected ? "true" : undefined}
                  className={cn(
                    "flex w-full min-h-11 items-center justify-between gap-3 rounded-lg border border-line bg-white p-3 text-left hover:border-accent hover:bg-accent-soft",
                    selected && "border-accent bg-accent-soft",
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{asset.name}</span>
                    <span className="block text-xs text-ink-soft">{asset.detail}</span>
                  </span>
                  {selected ? <CheckCircleIcon weight="fill" className="shrink-0 text-accent" aria-hidden="true" /> : null}
                </button>
              </li>
            );
          })}
          {assets.length === 0 ? <li className="rounded-lg bg-canvas p-3 text-sm text-ink-soft">Conjuntos geradores indisponíveis.</li> : null}
        </ul>
      </dialog>
    </>
  );
}
