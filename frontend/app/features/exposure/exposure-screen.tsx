import { Forecast60dSlot, SimpleHistoricalBarSlot } from "~/components/charts/exposure-charts";
import { CardSlot } from "~/components/charts/chart-frame";
import { HighlightList, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { AssetTopologyBody, type PlantTopologyContext, type PlantTopologyPlant } from "~/components/topology/asset-topology";
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
import { formatEvidence, numberFormatter } from "~/lib/format";
import { useExposure } from "~/state/use-exposure";

const sections: SectionNavItem[] = [
  { id: "secao-ativo", title: "Usina, conjunto e ponto de conexão" },
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

function technologyLabel(technology: "wind" | "solar") {
  return technology === "wind" ? "Eólica" : "Solar";
}

/** Renders the exact ISO parts published by the API, without reinterpreting them. */
function formatIsoMinute(value: string) {
  const [date, time = "00:00"] = value.split("T");
  const [year, month, day] = date.split("-");
  return `${day}/${month}/${year} ${time.slice(0, 5)}`;
}

function formatWindowRange(startsAt: string, endsAt: string) {
  return `${formatIsoMinute(startsAt)} a ${formatIsoMinute(endsAt)}`;
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

/**
 * The three non-overlapping 72-hour critical windows of the selected plant.
 * Each window shows its own period, expected MWh, restriction risk and the
 * impact of the already scheduled simulated maintenance.
 */
function CriticalWindows({ windows }: { windows: ExposureCriticalWindow[] }) {
  return (
    <ol data-critical-windows={windows.length} className="divide-y divide-line">
      {windows.map((window) => (
        <li key={window.rank} data-critical-window={window.rank} data-window-hours={window.windowHours} className="py-4 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-semibold text-ink">{`${window.rank}º período crítico`}</p>
            <p className="num text-2xl font-semibold leading-none text-ink">
              {numberFormatter.format(window.expectedCurtailedMwh)} <span className="font-sans text-xs font-semibold tracking-normal text-ink-soft">MWh</span>
            </p>
          </div>
          <p className="mt-1 text-sm leading-6 text-ink-soft">
            {formatWindowRange(window.startsAt, window.endsAt)} · {window.windowHours} horas · {window.intervalCount} intervalos de 30 min
          </p>
          <dl className="mt-3 grid gap-x-4 gap-y-1 text-xs leading-5 text-ink-soft sm:grid-cols-2">
            <div><dt className="inline">Risco de restrição: </dt><dd className="num inline text-ink">{numberFormatter.format(window.curtailmentProbability * 100)}%</dd></div>
            <div><dt className="inline">Alívio das manutenções agendadas: </dt><dd className="num inline text-ink">{numberFormatter.format(window.scheduledMaintenanceReliefMwh)} MWh</dd></div>
            <div><dt className="inline">Curtailment evitado: </dt><dd className="num inline text-ink">{numberFormatter.format(window.avoidedCurtailmentMwh)} MWh</dd></div>
            <div><dt className="inline">Alívio adicional da janela candidata: </dt><dd className="num inline text-ink">{window.candidateMaintenanceReliefMwh === null ? "Indisponível" : `${numberFormatter.format(window.candidateMaintenanceReliefMwh)} MWh`}</dd></div>
          </dl>
        </li>
      ))}
    </ol>
  );
}

export function ExposureScreen() {
  const { view, assets, loading, error, retry } = useExposure();

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
  const topologyAsset: Asset = {
    id: asset.assetId,
    name: asset.name,
    technology,
    location: asset.state,
    connectionPoint: asset.connectionPoint,
    anonymousEntities: asset.connectedAssetCount,
    telemetry: asset.operationalDataStatus === "simulated" ? "simulada" : "fornecida",
  };
  const selectedPlant: PlantTopologyPlant = { id: asset.assetId, name: asset.name, technology: asset.technology, groupId: asset.onsGroupId };
  const pointPlants: PlantTopologyPlant[] = [
    ...(pointContext?.entities ?? []).map((entity) => ({
      id: entity.plantId,
      name: entity.name,
      technology: entity.technology,
      groupId: asset.onsGroupId,
    })),
    selectedPlant,
  ];
  const groupPlants: PlantTopologyPlant[] = [
    ...assets
      .filter((candidate) => candidate.assetId !== asset.assetId && candidate.onsGroupId !== null && candidate.onsGroupId === asset.onsGroupId)
      .map((candidate) => ({ id: candidate.assetId, name: candidate.name, technology: candidate.technology, groupId: candidate.onsGroupId })),
    selectedPlant,
  ];
  const topologyContext: PlantTopologyContext = {
    onsGroupId: asset.onsGroupId,
    onsGroupName: asset.onsGroupName,
    pointPlants,
    groupPlants,
  };
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

  const identificationItems: HighlightItem[] = [
    { label: "Usina selecionada", value: asset.name },
    { label: "Identificador ONS da usina", value: asset.assetId },
    { label: "Tecnologia de geração", value: technology },
    { label: "Estado", value: asset.state },
    { label: "Capacidade cadastrada", ...metric(asset.capacityMw, "MW") },
    { label: "Capacidade operacional estimada", ...(simulatedTelemetry ? metric(simulatedTelemetry.operationalCapacityMw, "MW") : { value: "Indisponível" }) },
    { label: "Conjunto ONS", value: asset.onsGroupName ?? asset.onsGroupId ?? "Indisponível" },
    { label: "Ponto de conexão usado nesta análise", value: asset.connectionPoint },
    { label: "CEG da usina", value: asset.ceg ?? "Indisponível" },
    { label: "Última atualização do panorama", value: formatUpdate(view.lastDataUpdate) },
  ];

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
  const forecastDescription = "Um ponto por dia, com marcador e data, e a faixa de incerteza publicada ao redor da linha. O risco diário é a probabilidade de a usina sofrer alguma restrição naquele dia.";

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

  const weatherItems: HighlightItem[] = simulatedTelemetry
    ? [
        { label: `Condição meteorológica estimada (${simulatedTelemetry.weatherUnit})`, ...metric(simulatedTelemetry.weatherValue, simulatedTelemetry.weatherUnit), emphasis: "primary" },
        { label: "Participação de dias observados com restrição", ...displayMetric(curtailedDayShare), emphasis: "supporting" },
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
        <AnalysisSection id="secao-ativo" title="Usina, conjunto e ponto de conexão" illustration={illustration("secao-ativo")} analysis={analysis("secao-ativo")}>
          <Panel data-section-card aria-label="Usina selecionada, seus vínculos e sua telemetria">
            <CardSlot showHeader={false} title="Posição da usina na rede"><AssetTopologyBody asset={topologyAsset} context={topologyContext} /></CardSlot>
            <CardSlot title="Identificação e vínculos da usina" description="A usina é a entidade principal desta análise. O conjunto e o ponto aparecem como contexto.">
              <HighlightList label="Identificação e vínculos da usina" items={identificationItems} />
            </CardSlot>
            <CardSlot title="Telemetria operacional disponível" description="Estado operacional estimado da usina selecionada.">
              {telemetryItems.length ? (
                <HighlightList variant="metrics" label="Telemetria operacional da usina" items={telemetryItems} />
              ) : unavailable("A telemetria operacional desta usina não está disponível neste panorama.")}
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
              <HighlightList variant="metrics" label="Faixa estimada acumulada no horizonte" items={[
                { label: "Estimativa central", ...metric(forecast60d.totalExpectedMwh, "MWh"), emphasis: "primary" },
                { label: "Limite inferior da faixa", ...metric(forecast60d.totalLowerMwh, "MWh"), emphasis: "supporting" },
                { label: "Limite superior da faixa", ...metric(forecast60d.totalUpperMwh, "MWh"), emphasis: "supporting" },
                { label: "Geração potencial prevista da usina", ...metric(forecastTotals.potential, "MWh"), emphasis: "supporting" },
                { label: "Limite operacional estimado da usina", ...metric(forecastTotals.envelope, "MWh"), emphasis: "supporting" },
                { label: "Alívio das manutenções agendadas no horizonte", ...metric(forecastTotals.maintenanceRelief, "MWh"), emphasis: "supporting" },
              ]} />
            </div>
            <div className="mt-5 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Janelas críticas de 72 horas</h3>
              {forecast60d.criticalWindows72h.length ? <CriticalWindows windows={forecast60d.criticalWindows72h} /> : unavailable("O horizonte desta usina ainda não sustenta janelas críticas de 72 horas.")}
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-razao-origem" title="Condições do conjunto e do ponto de conexão" illustration={illustration("secao-razao-origem")} analysis={analysis("secao-razao-origem")}>
          <Panel data-section-card aria-label="Condições do conjunto e telemetria das usinas do ponto">
            <p className="mb-4 rounded-lg bg-canvas p-3 text-xs leading-5 text-ink-soft">As razões publicadas pertencem ao conjunto gerador e a energia das demais usinas do ponto é contexto sistêmico: ela não é atribuída à usina selecionada.</p>
            {reasons.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Condição associada ao corte no conjunto" description="Distribuição histórica por condição informada." data={reasons} /> : unavailable("O resumo diário usado no teste local não contém a classificação intervalar por motivo.")}
            {origins.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Abrangência registrada no conjunto" description="Origem registrada para os intervalos limitados." data={origins} /> : unavailable("O resumo diário usado no teste local não contém a classificação intervalar por origem.")}
            {modalities.points.length ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Forma de restrição registrada" description="Classificação apresentada separadamente das demais condições." data={modalities} /> : null}
            <div data-point-entities={pointContext?.entities.length ?? 0} className="mt-6 border-t border-line pt-5">
              <h3 className="text-sm font-semibold text-ink">Telemetria das usinas do ponto de conexão</h3>
              <p className="mt-1 text-sm leading-6 text-ink-soft">Todas as usinas ligadas ao ponto entram na pressão sistêmica estimada, com seus próprios valores.</p>
              {pointContext?.entities.length ? (
                <ul className="mt-4 divide-y divide-line text-sm">
                  {pointContext.entities.map((entity) => (
                    <li key={entity.plantId} data-point-entity={entity.plantId} className="py-3 first:pt-0 last:pb-0">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-medium text-ink">{entity.name}</span>
                        <span className="text-xs uppercase tracking-wide text-ink-soft">{technologyLabel(entity.technology)} · {numberFormatter.format(entity.capacityMw)} MW</span>
                      </div>
                      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs leading-5 text-ink-soft sm:grid-cols-3">
                        <div><dt className="inline">Geração disponível: </dt><dd className="num inline text-ink">{numberFormatter.format(entity.meanAvailableGenerationMw)} MW</dd></div>
                        <div><dt className="inline">Restrição média: </dt><dd className="num inline text-ink">{numberFormatter.format(entity.meanCurtailedGenerationMw)} MW</dd></div>
                        <div><dt className="inline">Dias com restrição: </dt><dd className="num inline text-ink">{formatEvidence(entity.restrictedDayShare * 100, "%")}</dd></div>
                        <div><dt className="inline">Manutenção agendada: </dt><dd className="num inline text-ink">{entity.scheduledMaintenanceIntervals} intervalos</dd></div>
                        <div><dt className="inline">Fator de manutenção aplicado: </dt><dd className="num inline text-ink">{numberFormatter.format(entity.scheduledMaintenanceDerate)}</dd></div>
                      </dl>
                    </li>
                  ))}
                </ul>
              ) : unavailable("A telemetria das usinas do ponto não está disponível neste panorama.")}
            </div>
            <div data-maintenance-comparison className="mt-6 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Comparação com e sem as manutenções já agendadas</h3>
              {maintenanceComparisonItems.length ? (
                <HighlightList variant="metrics" label="Comparação com e sem as manutenções já agendadas" items={maintenanceComparisonItems} />
              ) : unavailable("A agenda das manutenções agendadas das usinas do ponto não está disponível neste panorama.")}
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-recorrencia" title="Em quais dias e horários os cortes mais se repetem" illustration={illustration("secao-recorrencia")} analysis={analysis("secao-recorrencia")}>
          <Panel data-section-card aria-label="Recorrência da usina e relação com a meteorologia">
            {weekdays.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" emphasizeCount={2} slotClassName="pb-6 last:pb-0" title="Distribuição por dia da semana" description="Participação da estimativa histórica de energia restringida em cada dia da semana." data={weekdays} /> : unavailable("A série disponível não sustenta a distribuição por dia da semana.")}
            {hours.points.length ? <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" slotClassName="pb-6 last:pb-0" variant="line" title="Recorrência ao longo do dia" description="Frequência histórica das restrições por horário." data={hours} /> : unavailable("A série diária disponível não permite calcular uma distribuição por horário.")}
            <div data-weather-relationship className="mt-6 border-t border-line pt-5">
              <h3 className="mb-3 text-sm font-semibold text-ink">Relação com a condição meteorológica</h3>
              {weatherItems.length ? (
                <HighlightList variant="metrics" label="Condição meteorológica associada à usina" items={weatherItems} />
              ) : unavailable("A condição meteorológica desta usina não está disponível neste panorama.")}
              <p className="mt-3 text-xs leading-5 text-ink-soft">A série histórica disponível é diária: ela sustenta a recorrência por dia da semana, mas não permite afirmar uma relação horária entre vento ou irradiância e os cortes.</p>
            </div>
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
