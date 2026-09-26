import { useState } from "react";
import { Link } from "react-router";
import { ArrowRightIcon, CheckCircleIcon } from "@phosphor-icons/react";
import { AssetContext } from "~/components/layout/asset-context";
import { DecisionWorkspace } from "~/components/layout/decision-workspace";
import { EvidenceGuidance } from "~/components/evidence/guidance";
import { CapabilityUnavailable } from "~/components/evidence/capability-unavailable";
import { MaintenanceComparisonChart } from "~/components/charts/decision-charts";
import { Panel } from "~/components/ui/panel";
import { maintenanceGuidance, maintenancePackagesByAsset, reservationsByAsset } from "~/domain/fixtures";
import { requestMaintenanceRanking, residualProfileForWindow } from "~/domain/mock-api";
import { formatEvidence } from "~/lib/format";
import { useAnalysis } from "~/state/use-analysis";
import type { MaintenancePackage, MaintenanceWindow } from "~/domain/types";
import { InterventionForm, type InterventionValues } from "./intervention-form";
import { MaintenanceRanking } from "./maintenance-ranking";

export function MaintenanceScreen() {
  const { state, recordDecision, recordMaintenanceAnalysis } = useAnalysis();
  const materialized = maintenancePackagesByAsset[state.assetId];
  const [result, setResult] = useState<MaintenancePackage | null>(null);
  const [resultRevision, setResultRevision] = useState<number | null>(null);
  const [unsupportedRevision, setUnsupportedRevision] = useState<number | null>(null);
  const onRank = async (values: InterventionValues) => {
    const response = await requestMaintenanceRanking(state.assetId, values);
    setResult(response);
    recordMaintenanceAnalysis(response);
    setResultRevision(response ? state.selectionRevision : null);
    setUnsupportedRevision(response ? null : state.selectionRevision);
  };
  const onSelect = (window: MaintenanceWindow, justification: string) => {
    if (!result) return;
    const baseline = result.windows.find((candidate) => candidate.baseline);
    const residualProfileId = residualProfileForWindow(window.id);
    if (!baseline || !residualProfileId) return;
    recordDecision({ assetId: state.assetId, baselineId: baseline.id, selectedWindowId: window.id, justification, recordedAt: new Date().toISOString(), residualProfileId, energyDifference: window.differenceFromBaseline, monetaryDifference: window.monetaryDifferenceFromBaseline, premises: result.request });
  };
  const visibleResult = result?.assetId === state.assetId && resultRevision === state.selectionRevision ? result : null;
  const chosen = state.decision?.assetId === state.assetId && visibleResult ? visibleResult.windows.find((window) => window.id === state.decision?.selectedWindowId) ?? null : null;
  const hasPrice = visibleResult?.request.price !== null;
  const reservations = reservationsByAsset[state.assetId as keyof typeof reservationsByAsset] ?? reservationsByAsset["asset-wind"];
  return <DecisionWorkspace title="Perda prevista e manutenção" description="Informe a intervenção, compare a janela-base com alternativas elegíveis e registre a escolha." status="Ranking prototípico, não validado como previsão operacional" context={<AssetContext />}>
    {materialized ? <InterventionForm key={state.assetId} initialValues={materialized.request} onRank={onRank} /> : <CapabilityUnavailable title="Ranking ainda não integrado para este ativo">O ativo veio do catálogo real do ONS, mas o endpoint operacional de manutenção ainda não possui pacote compatível. Nenhuma fixture de outro ativo foi reutilizada.</CapabilityUnavailable>}
    {unsupportedRevision === state.selectionRevision ? <CapabilityUnavailable title="Combinação ainda não materializada">A demonstração não possui uma resposta da API para os parâmetros alterados. Restaure o perfil inicial do ativo para consultar o ranking; nenhum resultado anterior foi reutilizado.</CapabilityUnavailable> : null}
    {visibleResult && !hasPrice ? <CapabilityUnavailable title="Custo de oportunidade indisponível">O preço não foi informado. O ranking energético continua disponível; nenhum custo é inventado.</CapabilityUnavailable> : null}
    {visibleResult ? <><MaintenanceComparisonChart windows={visibleResult.windows} /><MaintenanceRanking key={visibleResult.id} windows={visibleResult.windows} hasPrice={hasPrice} onSelect={onSelect} /></> : <Panel title="Ranking aguardando consulta" description="Envie os parâmetros acima para obter o pacote materializado correspondente ao ativo selecionado." />}
    <Panel title="Reservas da demonstração" description="Lista simulada para demonstrar o efeito de reservas sobre o ranking. O CurtailLess não acessa planos privados de outras empresas e não executa coordenação multilateral.">
      <div className="grid gap-3 sm:grid-cols-2">{reservations.map((reservation) => <article key={reservation.id} className="rounded-lg border border-dashed border-warning bg-amber-50 p-4"><p className="font-semibold">Reserva simulada {reservation.id}</p><p className="mt-1 text-sm">{reservation.period}: {reservation.effect}.</p><span className="mt-3 inline-flex rounded-md border border-warning/30 px-2 py-1 text-xs font-semibold">simulado</span></article>)}</div>
      <p className="mt-4 text-xs text-ink-soft">Uma solicitação de coordenação ao ONS pode ser estudada como processo futuro separado.</p>
    </Panel>
    {chosen && state.decision ? <Panel title="Decisão registrada" description="O registro preserva a base, a escolha, as diferenças estimadas, a justificativa e as premissas vigentes."><div className="flex items-start gap-3"><CheckCircleIcon className="mt-1 shrink-0 text-accent" size={24} weight="fill" aria-hidden="true" /><div><p className="font-semibold">{chosen.baseline ? "Janela-base mantida" : `Alternativa ${chosen.rank} selecionada`}</p><p className="mt-1 text-sm text-ink-soft">Perfil residual {state.decision.residualProfileId} disponível para a triagem de bateria. Diferença energética: {formatEvidence(chosen.differenceFromBaseline.value, chosen.differenceFromBaseline.unit)}. Diferença monetária: {formatEvidence(chosen.monetaryDifferenceFromBaseline.value, chosen.monetaryDifferenceFromBaseline.unit)}.</p></div></div><Link className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-accent" to="/bateria">Avaliar bateria <ArrowRightIcon aria-hidden="true" /></Link></Panel> : null}
    <EvidenceGuidance guidance={maintenanceGuidance} />
  </DecisionWorkspace>;
}
