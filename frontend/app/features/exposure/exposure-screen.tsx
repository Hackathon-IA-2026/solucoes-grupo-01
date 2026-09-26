import { ArrowRightIcon } from "@phosphor-icons/react";
import { Link } from "react-router";
import { AssetContext } from "~/components/layout/asset-context";
import { DecisionWorkspace } from "~/components/layout/decision-workspace";
import { EvidenceMetric } from "~/components/evidence/evidence";
import { CapabilityUnavailable } from "~/components/evidence/capability-unavailable";
import { DataQualityPanel } from "~/components/evidence/data-quality";
import { EvidenceGuidance } from "~/components/evidence/guidance";
import { ExposureHistoryChart, SimpleHistoricalBar } from "~/components/charts/exposure-charts";
import { Panel } from "~/components/ui/panel";
import { assetExposureById, comparableWindowsByAsset, dataQualityByAsset, exposureGuidance } from "~/domain/fixtures";
import { formatEvidence } from "~/lib/format";
import { useAnalysis } from "~/state/use-analysis";

export function ExposureScreen() {
  const { state } = useAnalysis();
  const exposure = assetExposureById[state.assetId] ?? assetExposureById["asset-wind"];
  const comparableWindows = comparableWindowsByAsset[state.assetId as keyof typeof comparableWindowsByAsset] ?? comparableWindowsByAsset["asset-wind"];
  const solar = state.assetId === "asset-solar";
  const dataQuality = dataQualityByAsset[state.assetId] ?? dataQualityByAsset["asset-wind"];
  return (
    <DecisionWorkspace title="Exposição e perspectiva operacional" description="Entenda a energia não realizada, a recorrência histórica e a posição cadastral do ativo antes de escolher uma intervenção." status="Perspectiva histórica e sazonal, sem previsão operacional" context={<AssetContext />}>
      <div className="grid gap-3 sm:grid-cols-3">
        <EvidenceMetric label="Energia não realizada" evidence={exposure.summary.total} emphasis />
        <EvidenceMetric label="Razão caracterizada" evidence={exposure.summary.characterized} />
        <EvidenceMetric label="Eventos simultâneos" evidence={exposure.summary.simultaneous} />
      </div>
      <CapabilityUnavailable title={solar ? "Telemetria simulada" : "Telemetria do cliente não fornecida"}>
        {solar ? "A série própria desta demonstração é sintética e está marcada como simulada. Razão, origem e modalidade permanecem campos independentes." : "A análise usa apenas dados públicos do ONS. Geração e disponibilidade próprias aparecerão quando o cliente fornecer a telemetria."}
      </CapabilityUnavailable>
      <ExposureHistoryChart data={exposure.history} />
      <div className="grid gap-5 2xl:grid-cols-2">
        <SimpleHistoricalBar title="Razão registrada" description="Distribuição histórica da energia apurada por razão." data={exposure.reasons} />
        <SimpleHistoricalBar title="Origem registrada" description="Origem publicada sem inferência a partir da razão." data={exposure.origins} />
      </div>
      {exposure.modality ? <SimpleHistoricalBar title="Modalidade solar registrada" description="Modalidade _detail_tm apresentada separadamente da razão _tm e da origem." data={exposure.modality} /> : null}
      <div className="grid gap-5 2xl:grid-cols-2">
        <SimpleHistoricalBar title="Recorrência por dia da semana" description="Frequência histórica de patamares com restrição." data={exposure.seasonality} />
        <SimpleHistoricalBar title="Recorrência por hora" description="Perfil horário histórico para reconhecer concentração temporal." data={exposure.hourly} />
      </div>
      <SimpleHistoricalBar title="Perspectiva operacional de 30 dias" description="Frequência histórica de corte em datas e condições sazonais semelhantes. Resultado calculado, sem meteorologia ex ante." data={exposure.perspective} />
      <p className="rounded-lg border border-warning/30 bg-amber-50 p-4 text-sm text-amber-950">Esta perspectiva ainda não é uma previsão operacional. Não usa nem herda as métricas do modelo de seis horas.</p>
      <Panel title="Janelas históricas semelhantes" description="Janelas históricas de 72 horas usadas como contexto, sem transformar histórico em previsão.">
        <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><caption className="sr-only">Janelas históricas semelhantes ao período analisado</caption><thead><tr><th scope="col" className="border-b border-line p-3">Janela</th><th scope="col" className="border-b border-line p-3">Energia histórica</th><th scope="col" className="border-b border-line p-3">Frequência</th><th scope="col" className="border-b border-line p-3">Estado</th></tr></thead><tbody>{comparableWindows.map((window) => <tr key={window.label}><td className="border-b border-line/70 p-3 font-semibold">{window.label}</td><td className="num border-b border-line/70 p-3">{formatEvidence(window.energy.value, window.energy.unit)}</td><td className="num border-b border-line/70 p-3">{formatEvidence(window.eventFrequency.value, window.eventFrequency.unit)}</td><td className="border-b border-line/70 p-3">{window.energy.state}</td></tr>)}</tbody></table></div>
        <dl className="mt-3 grid gap-2 text-xs leading-5 text-ink-soft"><div><dt className="font-semibold text-ink">Energia histórica</dt><dd>Método: {comparableWindows[0].energy.method} Período: {comparableWindows[0].energy.period.label}. Fonte: {comparableWindows[0].energy.source}. Versão: {comparableWindows[0].energy.dataVersion}. Estado: {comparableWindows[0].energy.state}.</dd></div><div><dt className="font-semibold text-ink">Frequência</dt><dd>Método: {comparableWindows[0].eventFrequency.method} Período: {comparableWindows[0].eventFrequency.period.label}. Fonte: {comparableWindows[0].eventFrequency.source}. Versão: {comparableWindows[0].eventFrequency.dataVersion}. Estado: {comparableWindows[0].eventFrequency.state}.</dd></div></dl>
      </Panel>
      <Panel title="Simultaneidade histórica anonimizada" description="Comparação entre eventos exclusivos e simultâneos para o ativo selecionado.">
        <div className="grid gap-3 sm:grid-cols-3"><EvidenceMetric label="Exclusiva do ativo" evidence={exposure.summary.exclusive} /><EvidenceMetric label="Simultânea" evidence={exposure.summary.simultaneous} /><EvidenceMetric label="Entidades anonimizadas" evidence={exposure.summary.entityCount} /></div>
        <p className="mt-4 text-sm text-ink-soft">Associação histórica não comprova causalidade elétrica, limite do ponto ou compartilhamento de planos.</p>
      </Panel>
      <DataQualityPanel quality={dataQuality} />
      <EvidenceGuidance guidance={exposureGuidance} />
      <div className="flex justify-end"><Link className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-accent" to="/manutencao">Configurar intervenção <ArrowRightIcon aria-hidden="true" /></Link></div>
    </DecisionWorkspace>
  );
}
