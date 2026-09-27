import type { Asset } from "~/domain/types";
import { SolarNetworkIllustration } from "./solar-network-illustration";
import { WindNetworkIllustration } from "./wind-network-illustration";

export type EnergyNetworkIllustrationProps = {
  technology: Asset["technology"];
  sectionId: string;
  connectedCount: number;
};

export function EnergyNetworkIllustration({ technology, sectionId, connectedCount }: EnergyNetworkIllustrationProps) {
  return technology === "Solar"
    ? <SolarNetworkIllustration sectionId={sectionId} connectedCount={connectedCount} />
    : <WindNetworkIllustration sectionId={sectionId} connectedCount={connectedCount} />;
}
