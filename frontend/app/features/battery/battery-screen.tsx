import { BatteryChargingIcon, CurrencyDollarIcon, LightningIcon } from "@phosphor-icons/react";
import { HighlightList, type HighlightItem } from "~/components/evidence/highlight-list";
import { EnergyNetworkIllustration } from "~/components/illustrations/energy-network-illustration";
import { AnalysisSection } from "~/components/layout/analysis-section";
import { SectionNav, type SectionNavItem } from "~/components/layout/section-nav";
import { Button } from "~/components/ui/button";
import { Panel } from "~/components/ui/panel";
import type { ExposureAsset } from "~/domain/types";
import { numberFormatter } from "~/lib/format";
import { useExposure } from "~/state/use-exposure";
import { batteryEstimatesByAsset, type BatteryEstimate } from "./battery-demo";

const sections: SectionNavItem[] = [
  { id: "secao-contribuicao", title: "Contribuição estimada da bateria" },
  { id: "secao-retorno", title: "Retorno econômico estimado" },
];

export function BatteryScreen() {
  const { assets, selectedAssetId, loading, error, retry } = useExposure();
  const asset = assets.find((item) => item.assetId === selectedAssetId) ?? assets[0];

  if (!asset) {
    return (
      <div>
        <h1 className="sr-only">Bateria</h1>
        <SectionNav items={sections} />
        <div className="grid min-h-[60dvh] place-items-center">
          <Panel
            title={loading ? "Carregando usinas" : "Usinas temporariamente indisponíveis"}
            description={error ?? "Aguarde o carregamento das usinas individuais."}
          >
            {!loading ? <Button variant="primary" onClick={retry}>Tentar novamente</Button> : null}
          </Panel>
        </div>
      </div>
    );
  }

  const estimate = batteryEstimatesByAsset[asset.assetId];
  if (!estimate) {
    return (
      <div>
        <h1 className="sr-only">Bateria</h1>
        <SectionNav items={sections} />
        <div className="grid min-h-[60dvh] place-items-center">
          <Panel title="Estimativa ainda não preparada" description={`A configuração estática de ${asset.name} ainda não foi cadastrada.`} />
        </div>
      </div>
    );
  }

  return (
    <div data-battery-screen data-asset-id={asset.assetId}>
      <h1 className="sr-only">Bateria</h1>
      <SectionNav items={sections} />

      <AnalysisSection
        id="secao-contribuicao"
        title="Como uma bateria contribuiria para esta usina"
        illustration={<BatteryIllustration asset={asset} sectionId="secao-contribuicao" />}
        analysis={estimate.contributionAnalysis.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      >
        <BatteryContributionCard estimate={estimate} />
      </AnalysisSection>

      <AnalysisSection
        id="secao-retorno"
        title="Como o investimento estimado se paga"
        illustration={<BatteryIllustration asset={asset} sectionId="secao-retorno" />}
        analysis={estimate.returnAnalysis.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      >
        <BatteryReturnCard estimate={estimate} />
      </AnalysisSection>
    </div>
  );
}

function BatteryContributionCard({ estimate }: { estimate: BatteryEstimate }) {
  const items: HighlightItem[] = [
    { label: "Potência sugerida", value: numberFormatter.format(estimate.batteryPowerMw), unit: "MW", detail: `${numberFormatter.format(estimate.batteryPowerMw / estimate.plantCapacityMw * 100)}% da potência da usina` },
    { label: "Capacidade de armazenamento", value: numberFormatter.format(estimate.batteryEnergyMwh), unit: "MWh", detail: `${numberFormatter.format(estimate.dischargeHours)} horas de descarga` },
    { label: "Entrega anual estimada", value: numberFormatter.format(estimate.annualDeliveryMwh), unit: "MWh/ano", detail: `${numberFormatter.format(estimate.annualCycles)} ciclos anuais` },
    { label: "Eficiência de ciclo", value: numberFormatter.format(estimate.roundTripEfficiencyPct), unit: "%", detail: "Energia entregue em relação à energia carregada" },
    { label: "Disponibilidade considerada", value: numberFormatter.format(estimate.availabilityPct), unit: "%", detail: "Tempo anual disponível para operação" },
  ];

  return (
    <Panel data-section-card aria-label="Configuração estimada da bateria">
      <div className="mb-5 flex items-start gap-3 border-b border-line pb-5">
        <BatteryChargingIcon className="mt-0.5 shrink-0 text-accent" size={28} weight="duotone" aria-hidden="true" />
        <div>
          <h3 className="font-semibold text-ink">Sistema de armazenamento sugerido</h3>
          <p className="mt-1 text-sm leading-6 text-ink-soft">Configuração proporcional ao porte e ao perfil tecnológico da usina.</p>
        </div>
      </div>
      <HighlightList label="Indicadores técnicos estimados da bateria" items={items} />
    </Panel>
  );
}

function BatteryReturnCard({ estimate }: { estimate: BatteryEstimate }) {
  const items: HighlightItem[] = [
    { label: "Investimento estimado", value: money(estimate.capexMillionBrl), detail: "Equipamentos, integração e implantação" },
    { label: "Capacidade e leilões", value: money(estimate.capacityRevenueMillionBrl), unit: "/ano", detail: "Disponibilidade e compromissos de potência" },
    { label: "Arbitragem de energia", value: money(estimate.arbitrageRevenueMillionBrl), unit: "/ano", detail: "Carga e descarga entre horários" },
    { label: "Serviços e incentivos", value: money(estimate.servicesRevenueMillionBrl), unit: "/ano", detail: "Serviços ao sistema e incentivos aplicáveis" },
    { label: "Custo operacional", value: money(estimate.annualOpexMillionBrl), unit: "/ano", detail: "Operação e manutenção estimadas" },
    { label: "Benefício líquido anual", value: money(estimate.netAnnualBenefitMillionBrl), unit: "/ano", detail: "Receitas combinadas menos custo operacional" },
    { label: "Retorno simples", value: numberFormatter.format(estimate.simplePaybackYears), unit: "anos", detail: "Investimento dividido pelo benefício líquido anual" },
  ];

  return (
    <Panel data-section-card aria-label="Retorno econômico estimado da bateria">
      <div className="mb-5 rounded-lg bg-accent-soft p-4">
        <div className="flex items-start gap-3">
          <CurrencyDollarIcon className="mt-0.5 shrink-0 text-accent" size={24} weight="duotone" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-ink">Cálculo resumido do retorno</p>
            <p className="mt-2 text-sm leading-6 text-ink-soft">
              {money(estimate.grossRevenueMillionBrl)} em receitas anuais menos {money(estimate.annualOpexMillionBrl)} em custos resulta em {money(estimate.netAnnualBenefitMillionBrl)} por ano.
            </p>
          </div>
        </div>
      </div>
      <HighlightList label="Composição econômica estimada da bateria" items={items} />
      <div className="mt-5 flex items-start gap-3 border-t border-line pt-5 text-sm leading-6 text-ink-soft">
        <LightningIcon className="mt-0.5 shrink-0 text-accent" size={20} aria-hidden="true" />
        <p>O cenário combina leilões, capacidade, arbitragem, serviços ao sistema e incentivos. O curtailment orienta a operação, mas não sustenta sozinho o retorno.</p>
      </div>
    </Panel>
  );
}

function BatteryIllustration({ asset, sectionId }: { asset: ExposureAsset; sectionId: string }) {
  return (
    <div data-battery-illustration>
      <EnergyNetworkIllustration
        technology={asset.technology === "wind" ? "Eólica" : "Solar"}
        sectionId={sectionId}
        connectedCount={asset.connectedAssetCount}
        details={{ name: asset.name, groupName: `Conexão: ${asset.connectionPoint}` }}
      />
    </div>
  );
}

function money(value: number) {
  return `R$ ${numberFormatter.format(value)} mi`;
}
