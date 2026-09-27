export const MAX_CONNECTED_PLANTS = 3;

export type NetworkPoint = {
  x: number;
  y: number;
};

export type NetworkPlantSlot = NetworkPoint & {
  scale: number;
  phase: number;
};

export const NETWORK_VIEW_BOX = "0 0 1200 900";
export const NETWORK_SUBSTATION_ANCHOR = { x: 399, y: 700 } as const;
export const NETWORK_MAIN_ANCHOR = { x: 230.28, y: 684.58 } as const;
export const NETWORK_SOLAR_MAIN_ANCHOR = { x: 335.18, y: 574.46 } as const;
export const NETWORK_COUNT_ANCHOR = { x: 745, y: 650 } as const;
export const NETWORK_COUNT_SIZE = 86;
export const NETWORK_MAIN_SCALE = 1.4835;
export const NETWORK_SUBSTATION_SCALE = 0.7274;

/** Lower-left corner of the collector substation platform, in canvas coordinates. */
export const NETWORK_SUBSTATION_PORT = {
  x: NETWORK_SUBSTATION_ANCHOR.x - 139.66,
  y: NETWORK_SUBSTATION_ANCHOR.y + 2.91,
} as const;

/** Lower-left edge of the turbine base, measured from the wind plant anchor. */
export const WIND_MAIN_PORT_OFFSET = { x: -25.98, y: -16.78 } as const;

/** Lower-left edge of the solar ground pad, measured from the solar plant anchor. */
export const SOLAR_MAIN_PORT_OFFSET = { x: -105.98, y: -194.56 } as const;

const ISOMETRIC_SLOPE = 1 / Math.sqrt(3);

const CONNECTED_PLANT_SLOTS: readonly NetworkPlantSlot[] = [
  { x: 940, y: 590, scale: 0.34, phase: 20 },
  { x: 1040, y: 665, scale: 0.34, phase: 200 },
  { x: 1120, y: 740, scale: 0.34, phase: 75 },
];

function coordinate(value: number): number {
  return Number(value.toFixed(2));
}

export function getIsometricConnectionPath(start: NetworkPoint, end: NetworkPoint): string {
  const direction = end.y >= start.y ? 1 : -1;
  const elbowX = (start.x + end.x) / 2 + (end.y - start.y) / (2 * direction * ISOMETRIC_SLOPE);
  const elbowY = start.y + direction * ISOMETRIC_SLOPE * (elbowX - start.x);
  return `M ${start.x} ${start.y} L ${coordinate(elbowX)} ${coordinate(elbowY)} L ${end.x} ${end.y}`;
}

export function getConnectedPlantSlots(count: number): NetworkPlantSlot[] {
  const safeCount = Number.isFinite(count) ? Math.max(0, Math.min(MAX_CONNECTED_PLANTS, Math.trunc(count))) : 0;
  return CONNECTED_PLANT_SLOTS.slice(0, safeCount);
}

export function getNetworkConnectionPath({ x, y }: Pick<NetworkPlantSlot, "x" | "y">): string {
  return getIsometricConnectionPath(
    { x: NETWORK_COUNT_ANCHOR.x + NETWORK_COUNT_SIZE / 2, y: NETWORK_COUNT_ANCHOR.y },
    { x, y },
  );
}

/**
 * Cable between the collector substation and the main plant: leaves the
 * substation's lower-left corner, bends twice and arrives at the plant's
 * lower-left edge.
 */
export function getMainConnectionPath(start: NetworkPoint, end: NetworkPoint): string {
  const finalRun = 35;
  const elbowX = end.x - finalRun;
  const firstElbow = {
    x: elbowX,
    y: start.y + Math.abs(start.x - elbowX) * ISOMETRIC_SLOPE,
  };
  const secondElbow = {
    x: elbowX,
    y: end.y + finalRun * ISOMETRIC_SLOPE,
  };
  return [start, firstElbow, secondElbow, end]
    .map(({ x, y }, index) => `${index === 0 ? "M" : "L"} ${coordinate(x)} ${coordinate(y)}`)
    .join(" ");
}

function plantPort(anchor: NetworkPoint, offset: NetworkPoint): NetworkPoint {
  return { x: coordinate(anchor.x + offset.x), y: coordinate(anchor.y + offset.y) };
}

export const MAIN_NETWORK_CONNECTION = getMainConnectionPath(
  NETWORK_SUBSTATION_PORT,
  plantPort(NETWORK_MAIN_ANCHOR, WIND_MAIN_PORT_OFFSET),
);
export const SOLAR_MAIN_NETWORK_CONNECTION = getMainConnectionPath(
  NETWORK_SUBSTATION_PORT,
  plantPort(NETWORK_SOLAR_MAIN_ANCHOR, SOLAR_MAIN_PORT_OFFSET),
);
export const COUNT_NETWORK_CONNECTION = getIsometricConnectionPath(
  NETWORK_SUBSTATION_ANCHOR,
  { x: NETWORK_COUNT_ANCHOR.x - NETWORK_COUNT_SIZE / 2, y: NETWORK_COUNT_ANCHOR.y },
);
