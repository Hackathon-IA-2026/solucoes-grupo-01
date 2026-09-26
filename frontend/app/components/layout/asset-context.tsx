
import { useAnalysis } from "~/state/use-analysis";
import { AssetTopology } from "~/components/topology/asset-topology";
import { Panel } from "~/components/ui/panel";

export function AssetContext() {
  const { state, assets, assetsStatus } = useAnalysis();
  const asset = assets.find((item) => item.id === state.assetId);
  if (!asset) return <Panel title="Contexto do ativo" description={assetsStatus === "error" ? "Não foi possível consultar a API CurtaiLess." : "Carregando ativo materializado…"} />;
  return <div className="space-y-4"><AssetTopology asset={asset} /><Panel title="Contexto do ativo"><dl className="grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-ink-soft">Localização</dt><dd className="mt-1 font-semibold">{asset.location}</dd></div><div><dt className="text-xs text-ink-soft">Entidades no ponto</dt><dd className="num mt-1 font-semibold">Consulte a evidência abaixo</dd></div><div><dt className="text-xs text-ink-soft">Tecnologia</dt><dd className="mt-1 font-semibold">{asset.technology}</dd></div><div><dt className="text-xs text-ink-soft">Telemetria</dt><dd className="mt-1 font-semibold">{asset.telemetry}</dd></div></dl><p className="mt-3 text-xs leading-5 text-ink-soft">Cadastro do ativo carregado da API com modo {asset.dataMode}; contexto anonimizado carregado separadamente.</p></Panel></div>;
}
