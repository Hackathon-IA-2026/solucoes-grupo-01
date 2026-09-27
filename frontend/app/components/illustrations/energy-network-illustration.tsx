import type { Asset } from "~/domain/types";
import { SolarNetworkIllustration } from "./solar-network-illustration";
import { WindNetworkIllustration } from "./wind-network-illustration";

export type EnergyNetworkIllustrationDetails = {
  name: string;
  groupName?: string;
  state?: string;
  registeredCapacity?: string;
  operationalCapacity?: string;
  connectionPoint?: string;
  lastDataUpdate?: string;
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

  const hasMetadata = details.state || details.connectionPoint || details.registeredCapacity || details.operationalCapacity || details.lastDataUpdate;

  return (
    <div data-energy-illustration-with-details className="relative overflow-visible">
      {network}
      <div data-plant-identity-illustration className="pointer-events-none absolute left-0 top-0 z-10 w-[calc(50%-0.75rem)] bg-gradient-to-b from-canvas via-canvas/92 to-transparent px-5 pb-12 pt-4">
        <h3 className="text-xl font-semibold leading-7 text-ink">{details.name}</h3>
        {details.groupName ? <p className="mt-1 text-sm font-medium text-ink-soft">{details.groupName}</p> : null}
        {hasMetadata ? (
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] leading-4 text-ink-soft">
            {details.state ? <div><dt className="sr-only">Estado</dt><dd>{details.state}</dd></div> : null}
            {details.connectionPoint ? <div><dt className="sr-only">Ponto de conexão</dt><dd>{details.connectionPoint}</dd></div> : null}
            {details.registeredCapacity ? <div><dt className="sr-only">Capacidade cadastrada</dt><dd>{details.registeredCapacity}</dd></div> : null}
            {details.operationalCapacity ? <div><dt className="sr-only">Capacidade operacional</dt><dd>{details.operationalCapacity}</dd></div> : null}
            {details.lastDataUpdate ? <div className="col-span-2"><dt className="sr-only">Última atualização</dt><dd>Atualizado em {details.lastDataUpdate}</dd></div> : null}
          </dl>
        ) : null}
      </div>
    </div>
  );
}
