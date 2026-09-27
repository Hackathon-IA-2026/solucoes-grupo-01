export const MAX_CONNECTED_PLANTS = 8;

export type NetworkPlantSlot = {
  x: number;
  y: number;
  scale: number;
  phase: number;
  edge?: boolean;
};

export const NETWORK_VIEW_BOX = "0 0 600 900";
export const NETWORK_SUBSTATION_ANCHOR = { x: 300, y: 500 } as const;
export const NETWORK_MAIN_ANCHOR = { x: 300, y: 365 } as const;

const CONNECTED_PLANT_SLOTS: readonly NetworkPlantSlot[] = [
  { x: 90, y: 640, scale: 0.38, phase: 20 },
  { x: 450, y: 730, scale: 0.38, phase: 200 },
  { x: 210, y: 785, scale: 0.38, phase: 75 },
  { x: 510, y: 560, scale: 0.36, phase: 305 },
  { x: 350, y: 670, scale: 0.37, phase: 135 },
  { x: 95, y: 450, scale: 0.34, phase: 245 },
  { x: 560, y: 360, scale: 0.33, phase: 35, edge: true },
  { x: 35, y: 790, scale: 0.33, phase: 155, edge: true },
];

export function getConnectedPlantSlots(count: number): NetworkPlantSlot[] {
  const safeCount = Number.isFinite(count) ? Math.max(0, Math.min(MAX_CONNECTED_PLANTS, Math.trunc(count))) : 0;
  return CONNECTED_PLANT_SLOTS.slice(0, safeCount);
}

export function getNetworkConnectionPath({ x, y }: Pick<NetworkPlantSlot, "x" | "y">): string {
  const { x: targetX, y: targetY } = NETWORK_SUBSTATION_ANCHOR;
  const isometricSlope = 1 / Math.sqrt(3);
  const elbowX = x < targetX
    ? (y - targetY + isometricSlope * (x + targetX)) / (2 * isometricSlope)
    : (targetY - y + isometricSlope * (x + targetX)) / (2 * isometricSlope);
  const elbowY = x < targetX
    ? y - isometricSlope * (elbowX - x)
    : y + isometricSlope * (elbowX - x);
  const roundedElbowX = Math.round(elbowX * 10) / 10;
  const roundedElbowY = Math.round(elbowY * 10) / 10;
  return `M ${x} ${y} L ${roundedElbowX} ${roundedElbowY} L ${targetX} ${targetY}`;
}

export const MAIN_NETWORK_CONNECTION = getNetworkConnectionPath(NETWORK_MAIN_ANCHOR);
