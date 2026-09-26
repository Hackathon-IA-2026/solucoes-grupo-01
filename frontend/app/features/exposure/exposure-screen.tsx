import { useEffect, useState } from "react";
import { ArrowRightIcon } from "@phosphor-icons/react";
import { Link } from "react-router";
import { AssetContext } from "~/components/layout/asset-context";
import { DecisionWorkspace } from "~/components/layout/decision-workspace";
import { EvidenceMetric } from "~/components/evidence/evidence";
import { CapabilityUnavailable } from "~/components/evidence/capability-unavailable";
import { Panel } from "~/components/ui/panel";
import { getConfiguredCurtaiLessApi, mapNumericEvidence, type ApiExposure, type ApiHistoricalWindows, type ApiPointContext } from "~/domain/api-client";
import { formatEvidence } from "~/lib/format";
import { useAnalysis } from "~/state/use-analysis";

type EvidenceState = { exposure: ApiExposure; point: ApiPointContext; windows: ApiHistoricalWindows };
const PERIOD = { start: "2026-08-01", end: "2026-08-31" };

export function ExposureScreen() {
  const { state } = useAnalysis();
  const [result, setResult] = useState<{ assetId: string; evidence: EvidenceState } | null>(null);
  const [failure, setFailure] = useState<{ assetId: string; message: string } | null>(null);
  const evidence = result?.assetId === state.assetId ? result.evidence : null;
  const error = failure?.assetId === state.assetId ? failure.message : null;

  useEffect(() => {
    if (!state.assetId) return;
    let active = true;
    const assetId = state.assetId;
    const api = getConfiguredCurtaiLessApi();
    Promise.all([
      api.getExposure(state.assetId, PERIOD.start, PERIOD.end),
      api.getPointContext(state.assetId),
      api.getWindows(state.assetId, PERIOD.start, PERIOD.end, 72),
    ]).then(([exposure, point, windows]) => {
      if (active) {
        setResult({ assetId, evidence: { exposure, point, windows } });
        setFailure(null);
      }
    }).catch((reason: unknown) => {
      if (active) setFailure({ assetId, message: reason instanceof Error ? reason.message : "Falha ao consultar evidências" });
    });
    return () => { active = false; };
  }, [state.assetId]);

  return (
    <DecisionWorkspace title="Exposição histórica observada" description="Consulte energia não realizada e contexto anonimizado materializados a partir de dados públicos do ONS." status="Histórico observado; não é previsão operacional" context={<AssetContext />}>
      {!state.assetId ? <Panel title="Carregando ativos" description="Consultando o catálogo materializado na API CurtaiLess." /> : null}
      {error ? <CapabilityUnavailable title="Evidência pública indisponível">{error}. Nenhum valor demonstrativo foi usado como substituto.</CapabilityUnavailable> : null}
      {evidence ? <>
        <div className="grid gap-3 sm:grid-cols-3">
          <EvidenceMetric label="Energia não realizada" evidence={mapNumericEvidence(evidence.exposure.total_curtailed_energy)} emphasis />
          <EvidenceMetric label="Entidades anonimizadas" evidence={mapNumericEvidence(evidence.point.anonymized_entity_count)} />
          <EvidenceMetric label="Simultaneidade histórica" evidence={mapNumericEvidence(evidence.point.simultaneity_rate)} />
        </div>
        <CapabilityUnavailable title="Telemetria do cliente não fornecida">A análise usa apenas agregados públicos do ONS. Geração, disponibilidade, setpoint e eventos próprios não foram inferidos.</CapabilityUnavailable>
        <Panel title="Janelas históricas materializadas" description="Sinal mensal observado rateado para janelas de 72 horas; não é previsão ex ante.">
          <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><caption className="sr-only">Janelas históricas do ativo</caption><thead><tr><th className="border-b border-line p-3">Início</th><th className="border-b border-line p-3">Fim</th><th className="border-b border-line p-3">Energia histórica</th><th className="border-b border-line p-3">Estado</th></tr></thead><tbody>{evidence.windows.windows.map((window) => { const item = mapNumericEvidence(window.expected_curtailed_energy); return <tr key={window.start}><td className="border-b border-line/70 p-3">{window.start}</td><td className="border-b border-line/70 p-3">{window.end}</td><td className="num border-b border-line/70 p-3">{formatEvidence(item.value, item.unit)}</td><td className="border-b border-line/70 p-3">{item.state}</td></tr>; })}</tbody></table></div>
          <p className="mt-3 text-xs leading-5 text-ink-soft">{evidence.windows.limitations.join(" ")}</p>
        </Panel>
        <Panel title="Proveniência e limites">
          <dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-xs text-ink-soft">Modo</dt><dd className="font-semibold">{evidence.exposure.data_mode}</dd></div><div><dt className="text-xs text-ink-soft">Tipo</dt><dd className="font-semibold">{evidence.exposure.perspective_type}</dd></div><div><dt className="text-xs text-ink-soft">Fonte</dt><dd className="font-semibold">{evidence.exposure.total_curtailed_energy.source}</dd></div><div><dt className="text-xs text-ink-soft">Versão</dt><dd className="font-semibold">{evidence.exposure.total_curtailed_energy.data_version}</dd></div></dl>
          <p className="mt-4 text-sm text-ink-soft">{evidence.exposure.limitations.join(" ")} {evidence.point.limitations.join(" ")}</p>
        </Panel>
        <div className="flex justify-end"><Link className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-accent" to="/manutencao">Avaliar próxima etapa <ArrowRightIcon aria-hidden="true" /></Link></div>
      </> : state.assetId && !error ? <Panel title="Carregando evidências" description="Consultando exposição, contexto do ponto e janelas históricas na API." /> : null}
    </DecisionWorkspace>
  );
}
