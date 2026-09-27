import { Forecast60dSlot, SimpleHistoricalBarSlot } from "~/components/charts/exposure-charts";
import { CardSlot } from "~/components/charts/chart-frame";
import { HighlightList, MetricComposition, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { AssetTopologyBody } from "~/components/topology/asset-topology";
import { Panel } from "~/components/ui/panel";
import type { Asset, ChartDataset, EvidenceMetadata, ExposureDistribution, ExposureMetric } from "~/domain/types";
import { formatEvidence, numberFormatter } from "~/lib/format";
import { useExposure } from "~/state/use-exposure";

const sections: SectionNavItem[] = [
  { id: "secao-ativo", title: "Onde a usina está conectada" },
  { id: "secao-resumo", title: "O impacto observado na usina" },
  { id: "secao-previsao", title: "Previsão de curtailment para 60 dias" },
  { id: "secao-razao-origem", title: "Condições associadas aos cortes" },
  { id: "secao-recorrencia", title: "Dias e horários de maior recorrência" },
  { id: "secao-qualidade", title: "Abrangência do padrão e confiança" },
];

const reasonLabels: Record<string, string> = {
  ENE: "Condição energética do sistema",
  REL: "Confiabilidade da rede",
  CNF: "Indisponibilidade externa",
  NC: "Motivo não informado",
};

function metric(value: number | null, unit: string) {
  return value === null ? { value: "Indisponível" } : { value: numberFormatter.format(value), unit };
}

function evidence(unit: string, start: string, end: string, state: EvidenceMetadata["state"] = "calculado"): EvidenceMetadata {
  return {
    unit,
    period: { start, end, label: `${start} a ${end}` },
    source: "Análise CurtaiLess",
    dataVersion: end,
    method: "materializado no backend",
    state,
  };
}

function dataset(points: ExposureDistribution[], unit: string, start: string, end: string, labels: Record<string, string> = {}): ChartDataset {
  return {
    points: points.map((point) => ({ label: labels[point.label] ?? point.label, value: point.value })),
    evidence: evidence(unit, start, end),
  };
}

function unavailable(message: string) {
  return <div className="rounded-lg border border-line bg-canvas p-4 text-sm leading-6 text-ink-soft">{message}</div>;
}

function formatUpdate(value: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
}

function displayMetric(value: ExposureMetric) {
  return metric(value.value, value.unit);
}

function ExposureLoading() {
  return (
    <div aria-busy="true" aria-label="Carregando análise de Exposição">
      <h1 className="sr-only">Exposição</h1>
      <SectionNav items={sections} />
      {sections.map((section) => (
        <AnalysisSection
          id={section.id}
          key={section.id}
          title={section.title}
          illustration={<div aria-hidden="true" className="h-72 motion-safe:animate-pulse rounded-xl bg-line/50" />}
          analysis={(
            <div aria-hidden="true" className="space-y-3">
              <div className="h-4 w-full motion-safe:animate-pulse rounded bg-line/70" />
              <div className="h-4 w-4/5 motion-safe:animate-pulse rounded bg-line/70" />
            </div>
          )}
        >
          <Panel data-section-card aria-label={`${section.title}: carregando`}>
            <div aria-hidden="true" className="space-y-4">
              <div className="h-8 w-2/3 motion-safe:animate-pulse rounded bg-line/70" />
              <div className="h-32 w-full motion-safe:animate-pulse rounded bg-line/50" />
              <div className="h-8 w-full motion-safe:animate-pulse rounded bg-line/70" />
            </div>
          </Panel>
        </AnalysisSection>
      ))}
    </div>
  );
}

export function ExposureScreen() {
  const { view, loading, error, retry } = useExposure();

  if (loading && !view) return <ExposureLoading />;
  if (error && !view) {
    return (
      <div className="grid min-h-[60dvh] place-items-center px-4">
        <Panel title="Análise temporariamente indisponível" description="O frontend não substitui uma falha da API por dados demonstrativos ocultos.">
          <button type="button" onClick={retry} className="min-h-11 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:bg-ink">Tentar novamente</button>
        </Panel>
      </div>
    );
  }
  if (!view) return null;

  const { asset, observedImpact, forecast60d, associatedConditions, recurrence, quality, narrative } = view;
  const technology: Asset["technology"] = asset.technology === "wind" ? "Eólica" : "Solar";
  const topologyAsset: Asset = {
    id: asset.assetId,
    name: asset.name,
    technology,
    location: asset.state,
    connectionPoint: asset.connectionPoint,
    anonymousEntities: asset.connectedAssetCount,
    telemetry: asset.operationalDataStatus === "simulated" ? "simulada" : "fornecida",
  };
  const analysis = (id: keyof typeof narrative) => narrative[id].map((paragraph) => <p key={paragraph}>{paragraph}</p>);
  const illustration = (sectionId: string) => (
    <EnergyNetworkIllustration technology={technology} sectionId={sectionId} connectedCount={asset.connectedAssetCount} />
  );
  const forecastData: ChartDataset = {
    points: forecast60d.points.map((point, index) => ({
      label: index % 7 === 0 ? new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", timeZone: "UTC" }).format(new Date(`${point.forecastDate}T00:00:00Z`)) : "",
      value: Math.round(point.curtailmentProbability * 1000) / 10,
    })),
    evidence: evidence("%", forecast60d.start ?? "", forecast60d.end ?? "", "simulado"),
  };
  const forecastHighlights: HighlightItem[] = forecast60d.topWindows.map((window, index) => ({
    label: `${window.start} a ${window.end}`,
    value: numberFormatter.format(window.meanProbability * 100),
    unit: "%",
    detail: `${numberFormatter.format(window.expectedCurtailedMwh)} MWh esperados no cenário`,
    emphasis: index === 0 ? "primary" : "supporting",
  }));
  const periodStart = observedImpact.periodStart;
  const periodEnd = observedImpact.periodEnd;
  const reasons = dataset(associatedConditions.reasons, "%", periodStart, periodEnd, reasonLabels);
  const origins = dataset(associatedConditions.origins, "%", periodStart, periodEnd);
  const modalities = dataset(associatedConditions.modalities, "%", periodStart, periodEnd);
  const weekdays = dataset(recurrence.weekdays, "%", periodStart, periodEnd);
  const hours = dataset(recurrence.hours, "%", periodStart, periodEnd);

  return (
    <div data-exposure-screen data-asset-id={asset.assetId}>
      <h1 className="sr-only">Exposição</h1>
      <SectionNav items={sections} />
      <div>
        <AnalysisSection id="secao-ativo" title="Onde a usina está conectada" illustration={illustration("secao-ativo")} analysis={analysis("secao-ativo")}>
          <Panel data-section-card aria-label="Contexto da usina e do ponto de conexão">
            <CardSlot showHeader={false} title="Usina e ponto de conexão"><AssetTopologyBody asset={topologyAsset} /></CardSlot>
            <CardSlot showHeader={false} title="Informações da usina">
              <HighlightList label="Informações da usina" items={[
                { label: "Local da usina", value: asset.state },
                { label: "Tecnologia de geração", value: technology },
                { label: "Ponto usado nesta análise", value: asset.connectionPoint },
                { label: "Outras usinas ou conjuntos associados ao ponto", value: String(asset.connectedAssetCount) },
                { label: "Dados operacionais", value: asset.operationalDataStatus === "simulated" ? "Simulados" : "Conectados", detail: asset.operationalDataStatus === "simulated" ? "Nesta demonstração" : undefined },
                { label: "Última atualização dos dados", value: formatUpdate(view.lastDataUpdate) },
              ]} />
            </CardSlot>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-resumo" title="O impacto observado na usina" illustration={illustration("secao-resumo")} analysis={analysis("secao-resumo")}>
          <Panel data-section-card aria-label="Destaques do impacto observado na usina">
            <HighlightList variant="metrics" label="Destaques do impacto observado" items={[
              { label: "Geração potencial que deixou de ser produzida", ...displayMetric(observedImpact.totalCurtailedEnergy), emphasis: "hero" },
              { label: "Volume com motivo informado", ...displayMetric(observedImpact.characterizedShare), detail: "Parcela interpretável pelas condições registradas.", emphasis: "primary" },
              { label: "Padrão compartilhado no ponto", ...displayMetric(observedImpact.simultaneousShare), detail: "Participação estimada de outros ativos ligados ao ponto.", emphasis: "primary" },
            ]} />
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-previsao" title="Previsão de curtailment para os próximos 60 dias" illustration={illustration("secao-previsao")} analysis={analysis("secao-previsao")}>
          <Panel data-section-card aria-label="Previsão demonstrativa de curtailment para 60 dias">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-soft">Cenário demonstrativo</p>
            {forecast60d.status === "unavailable" ? unavailable("O cenário de 60 dias ainda não foi materializado para esta usina.") : <Forecast60dSlot data={forecastData} />}
            <div className="mt-5 border-t border-line pt-5">
              <HighlightList variant="metrics" label="Períodos com maior chance simulada" items={forecastHighlights} />
            </div>
            <div className="mt-5 border-t border-line pt-5">
              <HighlightList variant="metrics" label="Faixa estimada acumulada" items={[
                { label: "Estimativa central", ...metric(forecast60d.totalExpectedMwh, "MWh"), emphasis: "primary" },
                { label: "Limite inferior da faixa", ...metric(forecast60d.totalLowerMwh, "MWh"), emphasis: "supporting" },
                { label: "Limite superior da faixa", ...metric(forecast60d.totalUpperMwh, "MWh"), emphasis: "supporting" },
              ]} />
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-razao-origem" title="Quais condições aparecem junto dos cortes" illustration={illustration("secao-razao-origem")} analysis={analysis("secao-razao-origem")}>
          <Panel data-section-card aria-label="Condições associadas aos cortes">
            {reasons.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Condição associada ao corte" description="Distribuição histórica por condição informada." data={reasons} /> : unavailable("A distribuição por condição depende da materialização do histórico público.")}
            {origins.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Abrangência registrada" description="Origem registrada para os intervalos limitados." data={origins} /> : unavailable("A distribuição por origem ainda não está disponível para esta usina.")}
            {modalities.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Forma de restrição registrada" description="Classificação apresentada separadamente das demais condições." data={modalities} /> : null}
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-recorrencia" title="Em quais dias e horários os cortes mais se repetem" illustration={illustration("secao-recorrencia")} analysis={analysis("secao-recorrencia")}>
          <Panel data-section-card aria-label="Dias e horários de maior recorrência">
            {weekdays.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" emphasizeCount={2} slotClassName="pb-6 last:pb-0" title="Recorrência por dia da semana" description="Frequência histórica de intervalos com restrição em cada dia." data={weekdays} /> : unavailable("A base mensal disponível não sustenta a distribuição por dia da semana.")}
            {hours.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" slotClassName="pb-6 last:pb-0" variant="line" title="Recorrência ao longo do dia" description="Frequência histórica das restrições por horário." data={hours} /> : unavailable("A base mensal disponível não sustenta a distribuição por horário.")}
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-qualidade" title="Quanto desse padrão vem do ponto e quão completos estão os dados" illustration={illustration("secao-qualidade")} analysis={analysis("secao-qualidade")}>
          <Panel data-section-card aria-label="Abrangência do padrão e confiança nos dados">
            <MetricComposition label="Abrangência dos registros no ponto de conexão" items={[
              { label: "Compartilhados no ponto", value: observedImpact.simultaneousShare.value, displayValue: formatEvidence(observedImpact.simultaneousShare.value, observedImpact.simultaneousShare.unit) },
              { label: "Somente nesta usina", value: observedImpact.exclusiveShare.value, displayValue: formatEvidence(observedImpact.exclusiveShare.value, observedImpact.exclusiveShare.unit) },
            ]} />
            <div className="mt-6 border-t border-line pt-5">
              <HighlightList variant="metrics" label="Confiança e disponibilidade dos dados" items={[
                { label: "Histórico disponível para análise", ...displayMetric(quality.coverage), emphasis: "supporting" },
                { label: "Defasagem da atualização", ...displayMetric(quality.updateDelay), emphasis: "supporting" },
                { label: "Registros com informação ausente", ...displayMetric(quality.missingRate), emphasis: "supporting" },
                { label: "Registros repetidos", ...displayMetric(quality.duplicateCount), emphasis: "supporting" },
              ]} />
            </div>
          </Panel>
        </AnalysisSection>
      </div>
    </div>
  );
}
