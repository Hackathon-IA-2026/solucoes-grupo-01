import { Forecast60dSlot, SimpleHistoricalBarSlot } from "~/components/charts/exposure-charts";
import { CardSlot } from "~/components/charts/chart-frame";
import { HighlightList, MetricComposition, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { AssetTopologyBody } from "~/components/topology/asset-topology";
import { Panel } from "~/components/ui/panel";
import { assetExposureById, assets, dataQualityByAsset, forecastWindowsByAsset } from "~/domain/fixtures";
import type { ChartDataset } from "~/domain/types";
import { formatEvidence, numberFormatter } from "~/lib/format";
import { useAnalysis } from "~/state/use-analysis";
import { buildExposureNarrative } from "./exposure-narrative";

const sections: SectionNavItem[] = [
  { id: "secao-ativo", title: "Onde a usina está conectada" },
  { id: "secao-resumo", title: "O impacto observado na usina" },
  { id: "secao-previsao", title: "Previsão de curtailment para 60 dias" },
  { id: "secao-razao-origem", title: "Condições associadas aos cortes" },
  { id: "secao-recorrencia", title: "Dias e horários de maior recorrência" },
  { id: "secao-qualidade", title: "Abrangência do padrão e confiança" },
];

const reasonLabels: Record<string, string> = {
  "Razão energética": "Condição energética do sistema",
  Confiabilidade: "Confiabilidade da rede",
  "Indisponibilidade externa": "Indisponibilidade fora da usina",
  "Não caracterizada": "Motivo não informado",
};

const originLabels: Record<string, string> = {
  Sistêmica: "Condição do sistema",
  Local: "Condição próxima à usina",
  "Não informada": "Origem não informada",
};

function withClientLabels(data: ChartDataset, labels: Record<string, string>): ChartDataset {
  return { ...data, points: data.points.map((point) => ({ ...point, label: labels[point.label] ?? point.label })) };
}

function metric(value: number | null, unit: string) {
  return value === null ? { value: "Indisponível" } : { value: numberFormatter.format(value), unit };
}

export function ExposureScreen() {
  const { state } = useAnalysis();
  const asset = assets.find((item) => item.id === state.assetId) ?? assets[0];
  const exposure = assetExposureById[state.assetId] ?? assetExposureById["asset-wind"];
  const forecastWindows = forecastWindowsByAsset[state.assetId as keyof typeof forecastWindowsByAsset] ?? forecastWindowsByAsset["asset-wind"];
  const rankedForecastWindows = [...forecastWindows]
    .sort((a, b) => (b.likelihood.value ?? Number.NEGATIVE_INFINITY) - (a.likelihood.value ?? Number.NEGATIVE_INFINITY))
    .slice(0, 3);
  const dataQuality = dataQualityByAsset[state.assetId] ?? dataQualityByAsset["asset-wind"];
  const narrative = buildExposureNarrative({ asset, exposure, quality: dataQuality, windows: rankedForecastWindows });
  const analysis = (id: string) => narrative[id].map((paragraph) => <p key={paragraph}>{paragraph}</p>);
  const illustration = (sectionId: string) => (
    <EnergyNetworkIllustration technology={asset.technology} sectionId={sectionId} connectedCount={asset.anonymousEntities} />
  );
  const telemetryLabel = asset.telemetry === "ausente" ? "Ainda não conectados" : asset.telemetry === "simulada" ? "Simulados nesta demonstração" : "Conectados";
  const forecastHighlights: HighlightItem[] = rankedForecastWindows.map((window, index) => ({
    label: window.label,
    ...metric(window.likelihood.value, window.likelihood.unit),
    detail: window.summary,
    emphasis: index === 0 ? "primary" : "supporting",
  }));

  return (
    <div data-exposure-screen data-asset-id={asset.id}>
      <h1 className="sr-only">Exposição</h1>
      <SectionNav items={sections} />
      <div>
        <AnalysisSection id="secao-ativo" title="Onde a usina está conectada" illustration={illustration("secao-ativo")} analysis={analysis("secao-ativo")}>
          <Panel data-section-card aria-label="Contexto da usina e do ponto de conexão">
            <CardSlot showHeader={false} title="Usina e ponto de conexão"><AssetTopologyBody asset={asset} /></CardSlot>
            <CardSlot showHeader={false} title="Informações da usina">
              <HighlightList label="Informações da usina" items={[
                { label: "Local da usina", value: asset.location },
                { label: "Tecnologia de geração", value: asset.technology },
                { label: "Ponto usado nesta análise", value: asset.connectionPoint },
                { label: "Usinas ou conjuntos associados ao mesmo ponto", value: formatEvidence(exposure.summary.entityCount.value, exposure.summary.entityCount.unit) },
                { label: "Dados operacionais próprios", value: telemetryLabel },
              ]} />
            </CardSlot>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-resumo" title="O impacto observado na usina" illustration={illustration("secao-resumo")} analysis={analysis("secao-resumo")}>
          <Panel data-section-card aria-label="Destaques do impacto observado na usina">
            <HighlightList variant="metrics" label="Destaques do impacto observado" items={[
              { label: "Geração potencial que deixou de ser produzida", ...metric(exposure.summary.total.value, exposure.summary.total.unit), emphasis: "hero" },
              { label: "Volume em que o ONS informou o motivo do corte", ...metric(exposure.summary.characterized.value, exposure.summary.characterized.unit), detail: "Parcela do volume que pode ser interpretada pelas condições registradas.", emphasis: "primary" },
              { label: "Registros que também afetaram outras usinas do ponto", ...metric(exposure.summary.simultaneous.value, exposure.summary.simultaneous.unit), detail: "Participação do padrão compartilhado no ponto de conexão.", emphasis: "primary" },
            ]} />
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-previsao" title="Previsão de curtailment para os próximos 60 dias" illustration={illustration("secao-previsao")} analysis={analysis("secao-previsao")}>
          <Panel data-section-card aria-label="Previsão demonstrativa de curtailment para 60 dias">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-soft">Cenário demonstrativo</p>
            <Forecast60dSlot data={exposure.forecast60d} />
            <div className="mt-5 border-t border-line pt-5">
              <HighlightList variant="metrics" label="Janelas com maior chance simulada" items={forecastHighlights} />
            </div>
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-razao-origem" title="Quais condições aparecem junto dos cortes" illustration={illustration("secao-razao-origem")} analysis={analysis("secao-razao-origem")}>
          <Panel data-section-card aria-label="Condições associadas aos cortes">
            <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Condição associada ao corte" description="Distribuição histórica por condição informada." data={withClientLabels(exposure.reasons, reasonLabels)} />
            <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Abrangência registrada" description="Indica se o registro foi associado ao sistema ou ao entorno da usina." data={withClientLabels(exposure.origins, originLabels)} />
            {exposure.modality ? <SimpleHistoricalBarSlot compactHeader showTable={false} slotClassName="pb-6 last:pb-0" variant="horizontal" title="Forma de restrição registrada" description="Classificação apresentada separadamente das demais condições." data={exposure.modality} /> : null}
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-recorrencia" title="Em quais dias e horários os cortes mais se repetem" illustration={illustration("secao-recorrencia")} analysis={analysis("secao-recorrencia")}>
          <Panel data-section-card aria-label="Dias e horários de maior recorrência">
            <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" emphasizeCount={2} slotClassName="pb-6 last:pb-0" title="Recorrência por dia da semana" description="Frequência histórica de intervalos com restrição em cada dia." data={exposure.seasonality} />
            <SimpleHistoricalBarSlot compactHeader chartClassName="h-64" slotClassName="pb-6 last:pb-0" variant="line" title="Recorrência ao longo do dia" description="Frequência histórica das restrições por horário." data={exposure.hourly} />
          </Panel>
        </AnalysisSection>

        <AnalysisSection id="secao-qualidade" title="Quanto desse padrão vem do ponto e quão completos estão os dados" illustration={illustration("secao-qualidade")} analysis={analysis("secao-qualidade")}>
          <Panel data-section-card aria-label="Abrangência do padrão e confiança nos dados">
            <MetricComposition label="Abrangência dos registros no ponto de conexão" items={[
              { label: "Compartilhados no ponto", value: exposure.summary.simultaneous.value, displayValue: formatEvidence(exposure.summary.simultaneous.value, exposure.summary.simultaneous.unit) },
              { label: "Somente nesta usina", value: exposure.summary.exclusive.value, displayValue: formatEvidence(exposure.summary.exclusive.value, exposure.summary.exclusive.unit) },
            ]} />
            <div className="mt-6 border-t border-line pt-5">
              <HighlightList variant="metrics" label="Confiança e disponibilidade dos dados" items={[
                { label: "Usinas ou conjuntos observados no mesmo ponto", ...metric(exposure.summary.entityCount.value, exposure.summary.entityCount.unit), emphasis: "supporting" },
                { label: "Histórico disponível para análise", ...metric(dataQuality.coverage.value, dataQuality.coverage.unit), emphasis: "supporting" },
                { label: "Defasagem da atualização", ...metric(dataQuality.delay.value, dataQuality.delay.unit), emphasis: "supporting" },
                { label: "Registros com informação ausente", ...metric(dataQuality.nullRate.value, dataQuality.nullRate.unit), emphasis: "supporting" },
                { label: "Registros repetidos", ...metric(dataQuality.duplicates.value, dataQuality.duplicates.unit), emphasis: "supporting" },
              ]} />
            </div>
          </Panel>
        </AnalysisSection>
      </div>
    </div>
  );
}
