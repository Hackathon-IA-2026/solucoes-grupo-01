import type { Asset } from "~/domain/types";
import { SolarNetworkIllustration } from "./solar-network-illustration";
import { WindNetworkIllustration } from "./wind-network-illustration";

export type EnergyNetworkIllustrationDetails = {
  name: string;
  groupName: string;
  state: string;
  registeredCapacity: string;
  operationalCapacity: string;
  connectionPoint: string;
  lastDataUpdate: string;
};

export type EnergyNetworkIllustrationProps = {
  technology: Asset["technology"];
  sectionId: string;
  connectedCount: number;
  details?: EnergyNetworkIllustrationDetails;
};

export function EnergyNetworkIllustration({ technology, sectionId, connectedCount, details }: EnergyNetworkIllustrationProps) {
  const network = technology === "Solar"
    ? <SolarNetworkIllustration sectionId={sectionId} connectedCount={connectedCount} />
    : <WindNetworkIllustration sectionId={sectionId} connectedCount={connectedCount} />;

  if (!details) return network;

  return (
    <div data-energy-illustration-with-details className="relative overflow-hidden">
      {network}
      <div data-plant-identity-illustration className="pointer-events-none absolute inset-x-0 top-0 z-10 bg-gradient-to-b from-canvas via-canvas/95 to-transparent px-5 pb-20 pt-4">
        <h3 className="text-xl font-semibold leading-7 text-ink">{details.name}</h3>
        <p className="mt-1 text-sm font-medium text-ink-soft">{details.groupName}</p>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] leading-4 text-ink-soft">
          <div><dt className="sr-only">Estado</dt><dd>{details.state}</dd></div>
          <div><dt className="sr-only">Ponto de conexão</dt><dd>{details.connectionPoint}</dd></div>
          <div><dt className="sr-only">Capacidade cadastrada</dt><dd>{details.registeredCapacity}</dd></div>
          <div><dt className="sr-only">Capacidade operacional</dt><dd>{details.operationalCapacity}</dd></div>
          <div className="col-span-2"><dt className="sr-only">Última atualização</dt><dd>Atualizado em {details.lastDataUpdate}</dd></div>
        </dl>
      </div>
    </div>
  );
}
