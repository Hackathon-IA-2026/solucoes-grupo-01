import { useCallback, useEffect, useId, useRef } from "react";

import {
  MAIN_NETWORK_CONNECTION,
  NETWORK_MAIN_ANCHOR,
  NETWORK_SUBSTATION_ANCHOR,
  NETWORK_VIEW_BOX,
  getConnectedPlantSlots,
  getNetworkConnectionPath,
} from "./network-layout";

type SmilSvgElement = SVGSVGElement & {
  pauseAnimations: () => void;
  unpauseAnimations: () => void;
};

export function WindNetworkIllustration({
  sectionId,
  connectedCount,
}: {
  sectionId: string;
  connectedCount: number;
}) {
  const connectedPlantSlots = getConnectedPlantSlots(connectedCount);
  const connectedPlantCount = connectedPlantSlots.length;
  const connectedPlantLabel = connectedPlantCount === 1 ? "1 outra usina conectada" : `${connectedPlantCount} outras usinas conectadas`;
  const reactId = useId();
  const instanceId = `wind-${reactId.replace(/:/g, "")}`;
  const titleId = `${instanceId}-title`;
  const descriptionId = `${instanceId}-description`;
  const glowId = `${instanceId}-glow`;
  const turbineBodyId = `${instanceId}-turbine-body`;
  const rotorId = `${instanceId}-rotor`;
  const transformerId = `${instanceId}-transformer`;
  const breakerId = `${instanceId}-breaker`;

  const rootRef = useRef<HTMLElement>(null);
  const svgRef = useRef<SmilSvgElement | null>(null);
  const inViewRef = useRef(true);
  const visibleRef = useRef(true);
  const reducedMotionRef = useRef(false);

  const syncPlayback = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || typeof svg.pauseAnimations !== "function" || typeof svg.unpauseAnimations !== "function") return;

    if (reducedMotionRef.current || !inViewRef.current || !visibleRef.current) {
      svg.pauseAnimations();
    } else {
      svg.unpauseAnimations();
    }
  }, []);

  const setSvgRef = useCallback((svg: SmilSvgElement | null) => {
    svgRef.current = svg;
    if (!svg || typeof window === "undefined") return;
    reducedMotionRef.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    syncPlayback();
  }, [syncPlayback]);

  useEffect(() => {
    visibleRef.current = !document.hidden;
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotionRef.current = mediaQuery.matches;

    const handleVisibilityChange = () => {
      visibleRef.current = !document.hidden;
      syncPlayback();
    };
    const handleMotionPreference = (event: MediaQueryListEvent) => {
      reducedMotionRef.current = event.matches;
      syncPlayback();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    mediaQuery.addEventListener("change", handleMotionPreference);

    const root = rootRef.current;
    const observer = root && "IntersectionObserver" in window
      ? new IntersectionObserver(([entry]) => {
          inViewRef.current = entry?.isIntersecting ?? true;
          syncPlayback();
        }, { threshold: 0.05 })
      : null;

    if (root && observer) observer.observe(root);
    syncPlayback();

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      mediaQuery.removeEventListener("change", handleMotionPreference);
      observer?.disconnect();
    };
  }, [syncPlayback]);

  const scope = `[data-wind-instance="${instanceId}"]`;

  return (
    <figure
      ref={rootRef}
      data-energy-illustration="wind"
      data-illustration-section={sectionId}
      data-wind-instance={instanceId}
      className="wind-network-illustration"
    >
      <style>{`
        ${scope} {
          position: relative;
          display: block;
          width: 100%;
          max-width: none;
          margin: 0;
          overflow: visible;
          color: #26383c;
          isolation: isolate;
          pointer-events: none;
        }
        ${scope} .wind-canvas { display: block; width: 100%; height: auto; }
        ${scope} .wind-main,
        ${scope} .wind-detail,
        ${scope} .wind-wire,
        ${scope} .wind-fence,
        ${scope} .wind-ground {
          fill: none;
          stroke-linecap: round;
          stroke-linejoin: round;
          vector-effect: non-scaling-stroke;
        }
        ${scope} .wind-main { stroke: #26383c; stroke-width: 2.2; }
        ${scope} .wind-detail { stroke: #718185; stroke-width: 1.35; }
        ${scope} .wind-ground { stroke: #aab4b6; stroke-width: 1.2; stroke-dasharray: 5 6; }
        ${scope} .wind-fence { stroke: #718185; stroke-width: 1.05; stroke-dasharray: 3 5; opacity: .48; }
        ${scope} .wind-face {
          fill: #f4f6f5;
          stroke: #26383c;
          stroke-width: 1.8;
          stroke-linejoin: round;
          vector-effect: non-scaling-stroke;
        }
        ${scope} .wind-side {
          fill: #d1d8d7;
          stroke: #26383c;
          stroke-width: 1.8;
          stroke-linejoin: round;
          vector-effect: non-scaling-stroke;
        }
        ${scope} .wind-equipment { fill: #f4f6f5; stroke: #26383c; stroke-width: 1.8; stroke-linejoin: round; }
        ${scope} .wind-wire { stroke: #637377; stroke-width: 1.45; }
        ${scope} .wind-flow {
          fill: none;
          stroke: #18a86b;
          stroke-width: 1.8;
          stroke-dasharray: 22 176;
          stroke-linecap: round;
          vector-effect: non-scaling-stroke;
          filter: url(#${glowId});
        }
        ${scope} figcaption {
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border: 0;
        }
      `}</style>

      <svg
        ref={setSvgRef}
        className="wind-canvas"
        viewBox={NETWORK_VIEW_BOX}
        role="img"
        aria-labelledby={`${titleId} ${descriptionId}`}
      >
        <title id={titleId}>Rede eólica com 1 usina principal e {connectedPlantLabel}</title>
        <desc id={descriptionId}>Uma usina eólica principal e {connectedPlantLabel} convergem para uma subestação coletora detalhada. Conexões seguem os eixos isométricos, as pás giram e pulsos verdes mostram a energia chegando à rede.</desc>
        <defs>
          <filter id={glowId} x="-500%" y="-500%" width="1000%" height="1000%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <symbol id={turbineBodyId} viewBox="-120 -30 240 280">
            <path className="wind-face" d="M6 -8 L43 -29 L72 -12 L35 9 Z" />
            <path className="wind-side" d="M35 9 L72 -12 L72 2 L35 23 Z" />
            <path className="wind-face" d="M6 -8 L35 9 L35 23 L6 6 Z" />
            <path className="wind-detail" d="M47 -23 L61 -15 M42 -17 L58 -8 M38 -11 L53 -2" />
            <path className="wind-face" d="M-5 8 L7 8 L17 197 L0 207 L-16 198 Z" />
            <path className="wind-side" d="M7 8 L15 13 L17 197 L0 207 Z" />
            <path className="wind-face" d="M-35 218 L0 198 L35 218 L0 238 Z" />
            <path className="wind-side" d="M-35 218 L0 238 V246 L-35 226 Z" />
            <path className="wind-side" d="M0 238 L35 218 V226 L0 246 Z" />
          </symbol>
          <symbol id={rotorId} viewBox="-120 -120 240 240">
            <path className="wind-face" d="M0 -5 C-11 -30 -11 -82 0 -110 C13 -83 15 -35 7 -5 Z" />
            <path className="wind-face" d="M5 0 C32 -8 82 6 103 28 C73 34 29 20 3 8 Z" />
            <path className="wind-face" d="M-3 5 C-19 30 -58 67 -88 78 C-83 45 -47 9 -7 -3 Z" />
            <circle className="wind-face" cx="0" cy="0" r="12" />
            <circle cx="0" cy="0" r="4" fill="#26383c" />
          </symbol>
          <symbol id={transformerId} viewBox="-85 -105 170 210">
            <path className="wind-face" d="M-52 -8 L0 -38 L57 -5 L4 26 Z" />
            <path className="wind-side" d="M-52 -8 L4 26 L4 78 L-52 45 Z" />
            <path className="wind-face" d="M4 26 L57 -5 L57 47 L4 78 Z" />
            <path className="wind-main" d="M-62 2 L-52 8 M-62 12 L-52 18 M-62 22 L-52 28 M-62 32 L-52 38 M58 5 L69 -1 M58 16 L69 10 M58 27 L69 21 M58 38 L69 32" />
            <path className="wind-detail" d="M-68 -2 V40 M-62 2 V44 M69 -1 V36 M75 -5 V32" />
            <g className="wind-main"><path d="M-28 -22 V-59 M0 -38 V-78 M29 -22 V-59" /><path d="M-36 -31 H-20 M-35 -39 H-21 M-34 -47 H-22 M-9 -49 H9 M-8 -58 H8 M-7 -67 H7 M21 -31 H37 M22 -39 H36 M23 -47 H35" /></g>
            <path className="wind-face" d="M-45 -83 L14 -49 L42 -65 L-17 -99 Z" />
            <path className="wind-detail" d="M-45 -83 V-70 L14 -36 V-49 M42 -65 V-53 L14 -36" />
            <path className="wind-main" d="M-18 -64 L-4 -56 V-40 M-40 56 V69 M44 54 V67" />
          </symbol>
          <symbol id={breakerId} viewBox="-30 -75 60 150">
            <path className="wind-main" d="M0 54 V15 M0 -5 V-45" />
            <path className="wind-face" d="M-17 15 L0 5 L17 15 L0 25 Z" />
            <path className="wind-side" d="M-17 15 L0 25 V43 L-17 33 Z" />
            <path className="wind-face" d="M0 25 L17 15 V33 L0 43 Z" />
            <path className="wind-main" d="M-14 -7 H14 M-12 -17 H12 M-10 -27 H10" />
          </symbol>
        </defs>

        <path className="wind-ground" d="M300 360 L590 528 L300 696 L10 528 Z" opacity=".28" />
        <path className="wind-ground" d="M35 680 L300 527 L565 680 M120 780 L385 627 M480 795 L145 602" opacity=".11" />

        <g aria-hidden="true">
          <path data-network-connection="main" className="wind-wire" d={MAIN_NETWORK_CONNECTION} />
          <path className="wind-flow" d={MAIN_NETWORK_CONNECTION}>
            <animate attributeName="stroke-dashoffset" from="0" to="-198" dur="2.4s" repeatCount="indefinite" />
          </path>
          {connectedPlantSlots.map((slot) => {
            const connectionPath = getNetworkConnectionPath(slot);
            const connectionKey = `${slot.x}-${slot.y}`;
            const flowDuration = `${(2.7 + (slot.phase % 5) * 0.13).toFixed(2)}s`;
            const flowBegin = `${-(slot.phase % 120) / 40}s`;

            return (
              <g key={`connection-${connectionKey}`}>
                <path data-network-connection={connectionKey} className="wind-wire" d={connectionPath} opacity=".82" />
                <path className="wind-flow" d={connectionPath} opacity=".86">
                  <animate attributeName="stroke-dashoffset" from="0" to="-198" dur={flowDuration} begin={flowBegin} repeatCount="indefinite" />
                </path>
              </g>
            );
          })}
        </g>

        <g transform={`translate(${NETWORK_MAIN_ANCHOR.x} 120) scale(1.12)`}>
          <use className="wind-equipment" href={`#${turbineBodyId}`} x="-120" y="-30" width="240" height="280" />
          <g className="rotor-live"><use className="wind-equipment" href={`#${rotorId}`} x="-120" y="-120" width="240" height="240" /><animateTransform attributeName="transform" type="rotate" from="0 0 0" to="360 0 0" dur="8s" repeatCount="indefinite" /></g>
        </g>

        <g
          aria-label="Subestação coletora"
          transform={`translate(${NETWORK_SUBSTATION_ANCHOR.x - 330} ${NETWORK_SUBSTATION_ANCHOR.y - 324.5}) scale(.55)`}
        >
          <path className="wind-face" d="M600 476 L792 587 L600 698 L408 587 Z" />
          <path className="wind-side" d="M408 587 L600 698 V712 L408 601 Z" />
          <path className="wind-side" d="M600 698 L792 587 V601 L600 712 Z" />
          <path className="wind-fence" d="M600 488 L774 588 L600 688 L426 588 Z" />
          <g className="wind-detail" opacity=".5"><path d="M426 588 V545 M469 563 V520 M512 538 V495 M688 538 V495 M731 563 V520 M774 588 V545" /><path d="M442 598 V555 M486 623 V580 M530 648 V605 M670 648 V605 M714 623 V580 M758 598 V555" /></g>
          <g className="wind-main"><path d="M494 558 V451 M706 558 V451" /><path d="M494 451 L706 573" /><path d="M494 469 L706 591" opacity=".45" /><path d="M519 466 L508 482 M560 490 L549 506 M601 514 L590 530 M642 538 L631 554 M683 562 L672 578" /></g>
          <g transform="translate(510 573) scale(.72)"><use className="wind-equipment" href={`#${breakerId}`} x="-30" y="-75" width="60" height="150" /></g>
          <g transform="translate(690 573) scale(.72)"><use className="wind-equipment" href={`#${breakerId}`} x="-30" y="-75" width="60" height="150" /></g>
          <path className="wind-main" d="M510 523 L600 575 L690 523" />
          <path className="wind-detail" d="M531 535 L540 522 M555 549 L564 536 M579 563 L588 550 M621 563 L612 550 M645 549 L636 536 M669 535 L660 522" />
          <g transform="translate(530 626) scale(.66)"><use className="wind-equipment" href={`#${transformerId}`} x="-85" y="-105" width="170" height="210" /></g>
          <g transform="translate(650 661) scale(.66)"><use className="wind-equipment" href={`#${transformerId}`} x="-85" y="-105" width="170" height="210" /></g>
          <g><path className="wind-face" d="M676 603 L726 574 L766 597 L716 626 Z" /><path className="wind-side" d="M676 603 L716 626 V664 L676 641 Z" /><path className="wind-face" d="M716 626 L766 597 V635 L716 664 Z" /><path className="wind-detail" d="M728 630 L750 617 V638 L728 651 Z M687 614 L706 625 V644 L687 633 Z" /></g>
        </g>

        {connectedPlantSlots.map((slot) => {
          const plantKey = `${slot.x}-${slot.y}`;
          const rotationDuration = `${(8.4 + (slot.phase % 7) * 0.12).toFixed(2)}s`;

          return (
            <g
              key={`plant-${plantKey}`}
              data-connected-plant={plantKey}
              transform={`translate(${slot.x} ${slot.y}) scale(${slot.scale})`}
              opacity={slot.edge ? ".76" : ".86"}
            >
              <use className="wind-equipment" href={`#${turbineBodyId}`} x="-120" y="-30" width="240" height="280" />
              <g className="rotor-live">
                <use className="wind-equipment" href={`#${rotorId}`} x="-120" y="-120" width="240" height="240" />
                <animateTransform
                  attributeName="transform"
                  type="rotate"
                  from={`${slot.phase} 0 0`}
                  to={`${slot.phase + 360} 0 0`}
                  dur={rotationDuration}
                  repeatCount="indefinite"
                />
              </g>
            </g>
          );
        })}
      </svg>

      <figcaption>Rede eólica em outline isométrico, com 1 usina principal e {connectedPlantLabel}, além de uma subestação coletora detalhada conectada por circuitos sobre os eixos do plano isométrico.</figcaption>
    </figure>
  );
}
