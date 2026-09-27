import { useMemo, useState } from "react";
import { CalendarPlusIcon, CheckCircleIcon, WrenchIcon } from "@phosphor-icons/react";
import { CardSlot } from "~/components/charts/chart-frame";
import { HighlightList, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { Button } from "~/components/ui/button";
import { Panel } from "~/components/ui/panel";
import { maintenanceAnalysisCopyByAsset, maintenanceAnalysisSupplementByAsset } from "~/domain/analysis-copy";
import { maintenancePackagesByAsset } from "~/domain/fixtures";
import type { ExposureAsset, ExposureView } from "~/domain/types";
import { dateFormatter, numberFormatter } from "~/lib/format";
import { useExposure } from "~/state/use-exposure";
import {
  buildMaintenanceReductionSeries,
  estimatedDailyGeneration,
  scheduledPlantSummaries,
  suggestionsFromWindows,
  type MaintenanceSuggestion,
  type PlantMaintenanceBooking,
} from "./maintenance-demo";
import { MaintenanceReductionChart } from "./maintenance-reduction-chart";
import { MaintenanceSchedulingModal } from "./maintenance-scheduling-modal";

const sections: SectionNavItem[] = [
  { id: "secao-janelas", title: "Melhores datas para manutenção" },
  { id: "secao-reducao", title: "Redução já programada" },
  { id: "secao-ganho", title: "Ganho da usina e impacto geral" },
];

export function MaintenanceScreen() {
  const { assets, selectedAssetId, view, loading, error, retry } = useExposure();
  const asset = assets.find((item) => item.assetId === selectedAssetId) ?? assets[0];
  const currentView = view?.asset.assetId === asset?.assetId ? view : null;
  const maintenancePackage = maintenancePackagesByAsset[asset?.technology === "solar" ? "asset-solar" : "asset-wind"];
  const scenarioPricePerMwh = maintenancePackage.request.price ?? 300;
  const suggestions = useMemo(
    () => suggestionsFromWindows(maintenancePackage.windows, scenarioPricePerMwh),
    [maintenancePackage, scenarioPricePerMwh],
  );
  const plantDailyGenerationMwh = estimatedDailyGeneration(asset?.technology === "solar" ? "Solar" : "Eólica");
  const [bookings, setBookings] = useState<Record<string, PlantMaintenanceBooking>>({});
  const booking = asset ? bookings[asset.assetId] ?? null : null;
  const [modalOpen, setModalOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState<MaintenanceSuggestion | null>(null);

  const reductionPoints = useMemo(
    () => buildMaintenanceReductionSeries(booking, plantDailyGenerationMwh),
    [booking, plantDailyGenerationMwh],
  );
  const totals = useMemo(() => reductionPoints.reduce((total, point) => ({
    before: total.before + point.curtailmentBeforeMwh,
    otherPlants: total.otherPlants + point.scheduledReductionMwh,
    selectedPlant: total.selectedPlant + point.plantReductionMwh,
    residual: total.residual + point.residualCurtailmentMwh,
  }), { before: 0, otherPlants: 0, selectedPlant: 0, residual: 0 }), [reductionPoints]);

  const selectedSuggestion = booking?.suggestionId
    ? suggestions.find((suggestion) => suggestion.id === booking.suggestionId) ?? null
    : null;
  const totalReduction = totals.before - totals.residual;
  const averageAvoidedLoss = booking
    ? totals.selectedPlant / Math.max(1, booking.durationHours / 24)
    : 0;

  const openSuggestedWindow = (suggestion: MaintenanceSuggestion) => {
    setActiveSuggestion(suggestion);
    setModalOpen(true);
  };
  const openCustomWindow = () => {
    setActiveSuggestion(null);
    setModalOpen(true);
  };
  const confirmBooking = (nextBooking: PlantMaintenanceBooking) => {
    if (!asset) return;
    setBookings((current) => ({ ...current, [asset.assetId]: nextBooking }));
    setModalOpen(false);
  };

  const impactItems: HighlightItem[] = booking ? [
    { label: "Perda média evitada na janela", value: numberFormatter.format(averageAvoidedLoss), unit: "MWh/dia", emphasis: "primary" },
    { label: "Redução atribuída à usina", value: numberFormatter.format(totals.selectedPlant), unit: "MWh", emphasis: "supporting" },
    { label: "Redução geral programada", value: numberFormatter.format(totalReduction), unit: "MWh", emphasis: "supporting" },
    { label: "Participação da usina na redução", value: numberFormatter.format(totalReduction > 0 ? totals.selectedPlant / totalReduction * 100 : 0), unit: "%", emphasis: "supporting" },
    { label: "Curtailment residual no período", value: numberFormatter.format(totals.residual), unit: "MWh", emphasis: "supporting" },
  ] : [];

  if (!asset) {
    return (
      <div>
        <h1 className="sr-only">Manutenção</h1>
        <SectionNav items={sections} />
        <div className="grid min-h-[60dvh] place-items-center">
          <Panel title={loading ? "Carregando usinas" : "Usinas temporariamente indisponíveis"} description={error ?? "Aguarde o carregamento das usinas individuais."}>
            {!loading ? <Button variant="primary" onClick={retry}>Tentar novamente</Button> : null}
          </Panel>
        </div>
      </div>
    );
  }

  const staticAnalysis = maintenanceAnalysisCopyByAsset[asset.assetId];
  const staticSupplement = maintenanceAnalysisSupplementByAsset[asset.assetId];
  const analysis = (id: keyof typeof staticAnalysis) => [
    ...staticAnalysis[id],
    ...staticSupplement[id],
  ].map((paragraph) => <p key={paragraph}>{paragraph}</p>);

  return (
    <div data-maintenance-screen data-asset-id={asset.assetId}>
      <h1 className="sr-only">Manutenção</h1>
      <SectionNav items={sections} />

      <div>
        <AnalysisSection
          id="secao-janelas"
          title="Melhores datas para agendar a manutenção"
          illustration={<MaintenanceIllustration asset={asset} sectionId="secao-janelas" fullDetails={currentView} />}
          analysis={analysis("secao-janelas")}
        >
          <Panel data-section-card aria-label="Ranking das melhores datas para manutenção">
            <CardSlot title="Janelas sugeridas" description="Datas ranqueadas para uma intervenção de 24 horas.">
              <SuggestedWindowsList suggestions={suggestions} onSchedule={openSuggestedWindow} />
              <div className="mt-5 border-t border-line pt-4">
                <Button onClick={openCustomWindow}><CalendarPlusIcon size={18} aria-hidden="true" />Escolher outra data</Button>
              </div>
            </CardSlot>
          </Panel>
        </AnalysisSection>

        <AnalysisSection
          id="secao-reducao"
          title="Redução já programada pelas manutenções"
          illustration={<MaintenanceIllustration asset={asset} sectionId="secao-reducao" />}
          analysis={analysis("secao-reducao")}
        >
          <Panel data-section-card aria-label="Previsão de redução por manutenções">
            <CardSlot title="Curtailment antes e depois das manutenções" description="Passe o cursor sobre um dia para comparar geração reduzida e chance de curtailment.">
              <MaintenanceReductionChart points={reductionPoints} />
            </CardSlot>
            <CardSlot title="Agendamentos já considerados" description="Reduções demonstrativas incluídas no panorama inicial.">
              <ul className="grid gap-3 sm:grid-cols-2">
                {scheduledPlantSummaries.map((item) => (
                  <li key={item.plant} className="rounded-lg border border-line bg-canvas p-3 text-sm">
                    <p className="font-semibold text-ink">{item.plant}</p>
                    <p className="mt-1 text-xs leading-5 text-ink-soft">{item.period}. Redução estimada de {numberFormatter.format(item.reductionMwh)} MWh.</p>
                  </li>
                ))}
              </ul>
            </CardSlot>
          </Panel>
        </AnalysisSection>

        <AnalysisSection
          id="secao-ganho"
          title="Ganho da usina e impacto no panorama geral"
          illustration={<MaintenanceIllustration asset={asset} sectionId="secao-ganho" />}
          analysis={analysis("secao-ganho")}
        >
          <Panel data-section-card aria-label="Ganho estimado da usina">
            {booking ? (
              <>
                <CardSlot title="Agendamento confirmado" description={formatBooking(booking, selectedSuggestion)}>
                  <div className="flex items-start gap-3 rounded-lg bg-accent-soft p-4">
                    <CheckCircleIcon className="mt-0.5 shrink-0 text-accent" size={22} weight="fill" aria-hidden="true" />
                    <div>
                      <p className="font-semibold text-ink">{asset.name}</p>
                      <p className="mt-1 text-sm leading-6 text-ink-soft">{booking.observations}</p>
                    </div>
                  </div>
                </CardSlot>
                <CardSlot title="Resultado atualizado" description="O painel usa a geração diária estimada da usina no intervalo agendado.">
                  <HighlightList variant="metrics" label="Ganho estimado da usina e efeito geral" items={impactItems} />
                </CardSlot>
              </>
            ) : (
              <div className="py-10 text-center">
                <WrenchIcon className="mx-auto text-ink-soft" size={34} aria-hidden="true" />
                <h3 className="mt-4 font-semibold text-ink">Nenhuma manutenção agendada para esta usina</h3>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-soft">O painel permanecerá sem valores individuais até a confirmação de uma janela sugerida ou personalizada.</p>
                <Button className="mt-5" variant="primary" onClick={openCustomWindow}>Agendar manutenção</Button>
              </div>
            )}
          </Panel>
        </AnalysisSection>
      </div>

      <MaintenanceSchedulingModal
        open={modalOpen}
        assetName={asset.name}
        suggestion={activeSuggestion}
        scenarioPricePerMwh={scenarioPricePerMwh}
        onClose={() => setModalOpen(false)}
        onConfirm={confirmBooking}
      />
    </div>
  );
}

function MaintenanceIllustration({
  asset,
  sectionId,
  fullDetails,
}: {
  asset: ExposureAsset;
  sectionId: string;
  fullDetails?: ExposureView | null;
}) {
  const telemetry = fullDetails?.simulatedTelemetry;
  const details = fullDetails ? {
    name: asset.name,
    groupName: asset.onsGroupName ?? "Conjunto não informado",
    state: asset.state,
    registeredCapacity: asset.capacityMw === null ? "Capacidade indisponível" : `${numberFormatter.format(asset.capacityMw)} MW cadastrados`,
    operationalCapacity: telemetry ? `${numberFormatter.format(telemetry.operationalCapacityMw)} MW estimados` : "Estimativa indisponível",
    connectionPoint: asset.connectionPoint,
    lastDataUpdate: formatExposureUpdate(fullDetails.lastDataUpdate),
  } : {
    name: asset.name,
    groupName: `Conexão: ${asset.connectionPoint}`,
  };

  return (
    <div data-maintenance-illustration>
      <EnergyNetworkIllustration
        technology={asset.technology === "wind" ? "Eólica" : "Solar"}
        sectionId={sectionId}
        connectedCount={asset.connectedAssetCount}
        details={details}
      />
    </div>
  );
}

function SuggestedWindowsList({ suggestions, onSchedule }: { suggestions: MaintenanceSuggestion[]; onSchedule: (suggestion: MaintenanceSuggestion) => void }) {
  return (
    <ol className="space-y-3" aria-label="Ranking das melhores datas para agendar manutenção">
      {suggestions.map((suggestion) => (
        <li key={suggestion.id} className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line bg-canvas p-4">
          <div className="min-w-0 flex-1">
            <p className="text-lg font-semibold leading-6 text-ink">{rankLabel(suggestion.rank)}</p>
            <dl className="mt-2 grid gap-1 text-sm leading-5 text-ink sm:grid-cols-2 sm:gap-x-5">
              <div className="flex min-w-0 gap-1.5">
                <dt className="font-semibold">Início:</dt>
                <dd>{formatDateTime(suggestion.start)}</dd>
              </div>
              <div className="flex min-w-0 gap-1.5">
                <dt className="font-semibold">Fim:</dt>
                <dd>{formatDateTime(suggestion.end)}</dd>
              </div>
            </dl>
            <p className="mt-2 text-xs leading-5 text-ink-soft">{suggestion.reason} Perda evitada estimada: <span className="num font-semibold text-ink">{numberFormatter.format(suggestion.avoidedLossMwh)} MWh</span>.</p>
          </div>
          <Button className="shrink-0" variant="primary" onClick={() => onSchedule(suggestion)}>Agendar</Button>
        </li>
      ))}
    </ol>
  );
}

function rankLabel(rank: number) {
  if (rank === 1) return "MELHOR JANELA";
  if (rank === 2) return "2ª MELHOR";
  return "3ª MELHOR";
}

function formatExposureUpdate(value: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
}

function formatDateTime(value: string) {
  return `${dateFormatter.format(new Date(value))}, ${formatTime(value)}`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(value));
}

function formatBooking(booking: PlantMaintenanceBooking, suggestion: MaintenanceSuggestion | null) {
  const source = suggestion ? `Janela sugerida número ${suggestion.rank}` : "Data personalizada";
  return `${source}. Início em ${dateFormatter.format(new Date(booking.start))}, ${formatTime(booking.start)}. Duração de ${booking.durationHours} horas.`;
}
