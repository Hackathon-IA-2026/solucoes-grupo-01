import { Forecast60dSlot, SimpleHistoricalBarSlot } from "~/components/charts/exposure-charts";
import { CardSlot } from "~/components/charts/chart-frame";
import { HighlightList, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { Panel } from "~/components/ui/panel";
import type {
  Asset,
  ChartDataset,
  EvidenceMetadata,
  ExposureCriticalWindow,
  ExposureDistribution,
  ExposureMetric,
  ExposureNarrativeSectionId,
} from "~/domain/types";
import { numberFormatter } from "~/lib/format";
import { useExposure } from "~/state/use-exposure";

const sections: SectionNavItem[] = [
  { id: "secao-ativo", title: "Usina selecionada" },
  { id: "secao-resumo", title: "Impacto observado na usina" },
  { id: "secao-previsao", title: "Previsão de curtailment para 60 dias" },
  { id: "secao-razao-origem", title: "Condições do conjunto e do ponto" },
  { id: "secao-recorrencia", title: "Dias e horários de maior recorrência" },
  { id: "secao-qualidade", title: "Abrangência e qualidade dos dados da usina" },
];

/**
 * Weather providers keep useful skill for roughly the first 16 days. Beyond it
 * the published band widens; the quality section compares both stretches instead
 * of hiding the change.
 */
const USEFUL_WEATHER_HORIZON_DAYS = 16;

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

const monthNames = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
];

function parseIsoDay(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function formatWindowRange(start: string, end: string) {
  const first = parseIsoDay(start);
  const last = parseIsoDay(end);
  if (first.year === last.year && first.month === last.month) {
    return `${first.day} a ${last.day} de ${monthNames[first.month - 1]}`;
  }
  return `${first.day} de ${monthNames[first.month - 1]} a ${last.day} de ${monthNames[last.month - 1]}`;
}

function meanBandWidth(points: { lowerMwh: number; upperMwh: number }[], from: number, to: number) {
  const slice = points.slice(from, to);
  if (slice.length === 0) return null;
  return slice.reduce((total, point) => total + (point.upperMwh - point.lowerMwh), 0) / slice.length;
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

/** Three concise, non-overlapping 72-hour windows of the selected plant. */
function CriticalWindows({ windows }: { windows: ExposureCriticalWindow[] }) {
  return (
    <ol data-critical-windows={windows.length} className="divide-y divide-line">
      {windows.map((window) => (
        <li key={window.rank} data-critical-window={window.rank} data-window-hours={window.windowHours} className="flex flex-wrap items-baseline justify-between gap-3 py-4 first:pt-0 last:pb-0">
          <p className="text-sm font-semibold text-ink">{formatWindowRange(window.start, window.end)}</p>
          <p className="text-sm text-ink-soft">
            Perda: <span className="num font-semibold text-ink">{numberFormatter.format(window.expectedCurtailedMwh)} MWh</span>
          </p>
        </li>
      ))}
    </ol>
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

  const { asset, observedImpact, forecast60d, associatedConditions, recurrence, quality, pointContext, simulatedTelemetry, narrative } = view;
  const technology: Asset["technology"] = asset.technology === "wind" ? "Eólica" : "Solar";
  const analysis = (id: ExposureNarrativeSectionId) => narrative[id].map((paragraph) => <p key={paragraph}>{paragraph}</p>);
  const illustration = (sectionId: string) => (
    <EnergyNetworkIllustration technology={technology} sectionId={sectionId} connectedCount={asset.connectedAssetCount} />
  );
  const periodStart = observedImpact.periodStart;
  const periodEnd = observedImpact.periodEnd;
  const reasons = dataset(associatedConditions.reasons, "%", periodStart, periodEnd, reasonLabels);
  const origins = dataset(associatedConditions.origins, "%", periodStart, periodEnd);
  const modalities = dataset(associatedConditions.modalities, "%", periodStart, periodEnd);
  const weekdays = dataset(recurrence.weekdays, "%", periodStart, periodEnd);
  const hours = dataset(recurrence.hours, "%", periodStart, periodEnd);
  const curtailedDayShare = observedImpact.curtailedDayShare ?? observedImpact.eventDayShare;
  const allocationCoverage = observedImpact.allocationCoverage ?? asset.allocationCoverage;
  const forecastPoints = forecast60d.points;
  const forecastTotals = {
    potential: forecastPoints.reduce((total, point) => total + point.potentialGenerationMwh, 0),
    envelope: forecastPoints.reduce((total, point) => total + point.acceptedGenerationEnvelopeMwh, 0),
    maintenanceRelief: forecastPoints.reduce((total, point) => total + point.scheduledMaintenanceReliefMwh, 0),
    avoided: forecastPoints.reduce((total, point) => total + point.avoidedCurtailmentMwh, 0),
  };
  const nearHorizonBand = meanBandWidth(forecastPoints, 0, USEFUL_WEATHER_HORIZON_DAYS);
  const farHorizonBand = meanBandWidth(forecastPoints, USEFUL_WEATHER_HORIZON_DAYS, forecastPoints.length);

  const telemetryItems: HighlightItem[] = simulatedTelemetry
    ? [
        { label: "Geração atual estimada", ...metric(simulatedTelemetry.generationMw, "MW"), emphasis: "primary" },
        { label: "Geração potencial estimada", ...metric(simulatedTelemetry.potentialGenerationMw, "MW") },
        { label: "Disponibilidade estimada", ...metric(simulatedTelemetry.availabilityMw, "MW") },
        { label: "Limite operacional estimado", ...metric(simulatedTelemetry.acceptedGenerationLimitMw, "MW") },
        { label: "Energia potencialmente restringida", ...metric(simulatedTelemetry.potentiallyCurtailedMw, "MW") },
        { label: "Condição meteorológica estimada", ...metric(simulatedTelemetry.weatherValue, simulatedTelemetry.weatherUnit) },
        { label: "Restrição em curso", value: simulatedTelemetry.restricted ? "Sim" : "Não" },
      ]
    : [];

  const summaryItems: HighlightItem[] = [
    { label: "Energia restringida estimada no histórico", ...displayMetric(observedImpact.totalCurtailedEnergy), detail: "Estimativa construída sobre o histórico público da própria usina.", emphasis: "hero" },
    { label: "Participação de dias com restrição", ...displayMetric(curtailedDayShare), emphasis: "primary" },
    { label: "Média dos últimos 7 dias observados", ...displayMetric(observedImpact.trailing7DayMean), emphasis: "primary" },
    { label: "Média dos últimos 30 dias observados", ...displayMetric(observedImpact.trailing30DayMean), emphasis: "primary" },
    { label: "Geração atual estimada", ...(simulatedTelemetry ? metric(simulatedTelemetry.generationMw, "MW") : { value: "Indisponível" }), emphasis: "supporting" },
    { label: "Capacidade operacional estimada", ...(simulatedTelemetry ? metric(simulatedTelemetry.operationalCapacityMw, "MW") : { value: "Indisponível" }), emphasis: "supporting" },
  ];

  const forecastEvidence = evidence("MWh/dia", forecast60d.start ?? periodStart, forecast60d.end ?? periodEnd, "simulado");
  const forecastDescription = "Geração potencial e limite operacional por dia, com uma marca de data por semana.";

  const maintenanceComparisonItems: HighlightItem[] = pointContext
    ? [
        { label: "Geração potencial estimada no ponto, com as manutenções já agendadas", ...metric(pointContext.potentialGenerationMw, "MW"), emphasis: "primary" },
        { label: "Geração potencial estimada no ponto sem as manutenções já agendadas", ...metric(pointContext.potentialGenerationMw + pointContext.scheduledMaintenanceReliefMw, "MW"), emphasis: "primary" },
        { label: "Alívio estimado das manutenções já agendadas", ...metric(pointContext.scheduledMaintenanceReliefMw, "MW") },
        { label: "Envelope de geração aceita no ponto", ...metric(pointContext.acceptedGenerationEnvelopeMw, "MW") },
        { label: "Excesso estimado no ponto", ...metric(pointContext.estimatedExcessMw, "MW") },
        { label: "Janelas de manutenção agendadas no ponto", ...metric(pointContext.scheduledMaintenanceWindowCount, "janelas") },
        { label: "Energia restringida evitada no horizonte", ...metric(forecastTotals.avoided, "MWh") },
      ]
    : [];

  const qualityItems: HighlightItem[] = [
    { label: "Histórico disponível para a usina", ...displayMetric(quality.coverage), emphasis: "primary" },
    { label: "Defasagem da atualização", ...displayMetric(quality.updateDelay) },
    { label: "Registros com informação ausente", ...displayMetric(quality.missingRate) },
    { label: "Registros repetidos", ...displayMetric(quality.duplicateCount) },
    { label: "Cobertura da alocação da usina", ...(allocationCoverage ? displayMetric(allocationCoverage) : { value: "Indisponível" }), emphasis: "primary" },
  ];

  const horizonItems: HighlightItem[] = [
    { label: `Amplitude média da faixa até o ${USEFUL_WEATHER_HORIZON_DAYS}º dia`, ...(nearHorizonBand === null ? { value: "Indisponível" } : metric(nearHorizonBand, "MWh/dia")), emphasis: "primary" },
    { label: "Amplitude média da faixa após o horizonte meteorológico útil", ...(farHorizonBand === null ? { value: "Indisponível" } : metric(farHorizonBand, "MWh/dia")), emphasis: "primary" },
  ];

  return (
    <div data-exposure-screen data-asset-id={asset.assetId}>
      <h1 className="sr-only">Exposição</h1>
      <SectionNav items={sections} />
      <div>
        <AnalysisSection
          id="secao-ativo"
          title="Usina selecionada"
          illustration={(
            <EnergyNetworkIllustration
              technology={technology}
              sectionId="secao-ativo"
              connectedCount={asset.connectedAssetCount}
              details={{
                name: asset.name,
                groupName: asset.onsGroupName ?? "Conjunto não informado",
                state: asset.state,
                registeredCapacity: asset.capacityMw === null ? "Capacidade indisponível" : `${numberFormatter.format(asset.capacityMw)} MW cadastrados`,
                operationalCapacity: simulatedTelemetry === null ? "Estimativa indisponível" : `${numberFormatter.format(simulatedTelemetry.operationalCapacityMw)} MW estimados`,
                connectionPoint: asset.connectionPoint,
                lastDataUpdate: formatUpdate(view.lastDataUpdate),
              }}
            />
          )}
          analysis={<p>A análise considera somente a usina selecionada.</p>}
        >
          <Panel data-section-card aria-label="Estimativas operacionais da usina selecionada">
            <CardSlot title="Estimativas operacionais" description="Valores estimados para a usina selecionada.">
              {telemetryItems.length ? (
                <HighlightList variant="metrics" label="Estimativas operacionais da usina" items={telemetryItems} />
              ) : unavailable("As estimativas operacionais desta usina não estão disponíveis neste panorama.")}
            </CardSlot>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-resumo" title="Impacto observado na usina" illustration={illustration("secao-resumo")} analysis={analysis("secao-resumo")}>
          <Panel data-section-card aria-label="Destaques do impacto observado na usina">
            <HighlightList variant="metrics" label="Destaques do impacto observado na usina" items={summaryItems} />
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-previsao" title="Previsão de curtailment para os próximos 60 dias" illustration={illustration("secao-previsao")} analysis={analysis("secao-previsao")}>
          <Panel data-section-card aria-label="Previsão de curtailment da usina para 60 dias">
            {forecast60d.status === "unavailable" || forecastPoints.length === 0 ? unavailable("O horizonte de 60 dias ainda não foi materializado para esta usina.") : <Forecast60dSlot points={forecastPoints} description={forecastDescription} evidence={forecastEvidence} />}
            <div className="mt-5 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Janelas críticas de 72 horas</h3>
              {forecast60d.criticalWindows72h.length ? <CriticalWindows windows={forecast60d.criticalWindows72h} /> : unavailable("O horizonte desta usina ainda não sustenta janelas críticas de 72 horas.")}
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-razao-origem" title="Condições do conjunto e do ponto de conexão" illustration={illustration("secao-razao-origem")} analysis={analysis("secao-razao-origem")}>
          <Panel data-section-card aria-label="Condições e estimativas operacionais">
            {reasons.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Condição associada ao corte no conjunto" description="Distribuição histórica por condição informada." data={reasons} /> : unavailable("O resumo diário usado no teste local não contém a classificação intervalar por motivo.")}
            {origins.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Abrangência registrada no conjunto" description="Origem registrada para os intervalos limitados." data={origins} /> : unavailable("O resumo diário usado no teste local não contém a classificação intervalar por origem.")}
            {modalities.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Forma de restrição registrada" description="Classificação apresentada separadamente das demais condições." data={modalities} /> : null}
            <div data-maintenance-comparison className="mt-6 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Comparação com e sem as manutenções já agendadas</h3>
              {maintenanceComparisonItems.length ? (
                <HighlightList variant="metrics" label="Comparação com e sem as manutenções já agendadas" items={maintenanceComparisonItems} />
              ) : unavailable("A agenda das manutenções agendadas das usinas do ponto não está disponível neste panorama.")}
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-recorrencia" title="Em quais dias e horários os cortes mais se repetem" illustration={illustration("secao-recorrencia")} analysis={analysis("secao-recorrencia")}>
          <Panel data-section-card aria-label="Recorrência da usina">
            {weekdays.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" emphasizeCount={2} slotClassName="pb-6 last:pb-0" title="Distribuição por dia da semana" description="Participação da estimativa histórica de energia restringida em cada dia da semana." data={weekdays} /> : unavailable("A série disponível não sustenta a distribuição por dia da semana.")}
            {hours.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" slotClassName="pb-6 last:pb-0" variant="line" title="Recorrência ao longo do dia" description="Frequência histórica das restrições por horário." data={hours} /> : unavailable("A série diária disponível não permite calcular uma distribuição por horário.")}
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-qualidade" title="Abrangência e qualidade dos dados da usina" illustration={illustration("secao-qualidade")} analysis={analysis("secao-qualidade")}>
          <Panel data-section-card aria-label="Abrangência e qualidade dos dados da usina">
            <HighlightList variant="metrics" label="Qualidade e cobertura dos dados da usina" items={qualityItems} />
            <div data-weather-horizon={USEFUL_WEATHER_HORIZON_DAYS} className="mt-6 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Incerteza após o horizonte meteorológico útil</h3>
              <HighlightList variant="metrics" label="Amplitude média da faixa estimada" items={horizonItems} />
              <p className="mt-3 text-xs leading-5 text-ink-soft">A amplitude é a diferença entre os limites superior e inferior publicados em cada dia. Ela é mais estreita no trecho apoiado pela previsão meteorológica e cresce depois do horizonte útil dessa previsão.</p>
            </div>
          </Panel>
        </AnalysisSection>
      </div>
    </div>
  );
}
