import { useCallback, useEffect, useId, useRef } from "react";
import {
  MAIN_NETWORK_CONNECTION,
  NETWORK_SUBSTATION_ANCHOR,
  NETWORK_VIEW_BOX,
  getConnectedPlantSlots,
  getNetworkConnectionPath,
} from "./network-layout";

type SmilSvgElement = SVGSVGElement & {
  pauseAnimations: () => void;
  unpauseAnimations: () => void;
};

type SolarNetworkIllustrationProps = {
  sectionId: string;
  connectedCount: number;
};

export function SolarNetworkIllustration({ sectionId, connectedCount }: SolarNetworkIllustrationProps) {
  const reactId = useId().replace(/:/g, "");
  const connectedPlantSlots = getConnectedPlantSlots(connectedCount);
  const titleId = `solar-title-${reactId}`;
  const descriptionId = `solar-description-${reactId}`;
  const glowId = `solar-glow-${reactId}`;
  const panelId = `solar-panel-${reactId}`;
  const standId = `solar-stand-${reactId}`;
  const transformerId = `solar-transformer-${reactId}`;
  const breakerId = `solar-breaker-${reactId}`;
  const svgRef = useRef<SmilSvgElement | null>(null);
  const rootRef = useRef<HTMLElement | null>(null);
  const conditionsRef = useRef({ inView: true, visible: true, reducedMotion: false });

  const syncAnimationState = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || typeof svg.pauseAnimations !== "function" || typeof svg.unpauseAnimations !== "function") return;

    const { inView, visible, reducedMotion } = conditionsRef.current;
    const shouldPause = reducedMotion || !inView || !visible;
    if (shouldPause) svg.pauseAnimations();
    else svg.unpauseAnimations();
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    conditionsRef.current.reducedMotion = mediaQuery.matches;
    conditionsRef.current.visible = !document.hidden;
    syncAnimationState();

    const handleVisibilityChange = () => {
      conditionsRef.current.visible = !document.hidden;
      syncAnimationState();
    };
    const handleMotionPreference = (event: MediaQueryListEvent) => {
      conditionsRef.current.reducedMotion = event.matches;
      syncAnimationState();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    mediaQuery.addEventListener("change", handleMotionPreference);

    const observer = "IntersectionObserver" in window
      ? new IntersectionObserver(
          ([entry]) => {
            conditionsRef.current.inView = entry?.isIntersecting ?? true;
            syncAnimationState();
          },
          { threshold: 0.05 },
        )
      : null;
    if (rootRef.current && observer) observer.observe(rootRef.current);

    return () => {
      observer?.disconnect();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      mediaQuery.removeEventListener("change", handleMotionPreference);
    };
  }, [syncAnimationState]);

  return (
    <figure
      ref={rootRef}
      data-energy-illustration="solar"
      data-illustration-section={sectionId}
      className="solar-network-illustration"
    >
      <svg
        ref={svgRef}
        className="solar-network-illustration__canvas"
        viewBox={NETWORK_VIEW_BOX}
        role="img"
        aria-labelledby={`${titleId} ${descriptionId}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <title id={titleId}>
          {`Uma usina solar principal e ${connectedPlantSlots.length} usinas conectadas a uma subestação`}
        </title>
        <desc id={descriptionId}>
          {`Uma usina solar principal e ${connectedPlantSlots.length} usinas solares menores estão conectadas a uma subestação coletora. Painéis fazem pequenos movimentos de rastreamento e segmentos verdes mostram a energia chegando à rede.`}
        </desc>
        <defs>
          <filter id={glowId} x="-500%" y="-500%" width="1000%" height="1000%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <symbol id={panelId} viewBox="-100 -60 200 120">
            <path d="M-92 10 L8 -48 L92 0 L-8 58 Z" fill="#dce5e3" stroke="#26383c" strokeWidth="2" strokeLinejoin="round" />
            <path d="M-59 -9 L25 39 M-26 -28 L58 20 M7 -47 L91 1 M-75 20 L25 -38 M-58 30 L42 -28 M-41 40 L59 -18 M-24 50 L76 -8" fill="none" stroke="#718185" strokeWidth="1.35" strokeLinecap="round" />
            <path d="M-92 10 L8 -48 L92 0 L-8 58 Z" fill="none" stroke="#26383c" strokeWidth="2" strokeLinejoin="round" />
          </symbol>
          <symbol id={standId} viewBox="-100 -20 200 150">
            <path className="main" d="M0 22 V92 M-16 104 L0 92 L18 104" />
            <path className="detail" d="M-46 94 L0 120 L46 94 M0 92 V120" />
            <path className="face" d="M-28 105 L0 89 L29 106 L0 122 Z" />
            <path className="side" d="M-28 105 L0 122 V130 L-28 113 Z" />
            <path className="side" d="M0 122 L29 106 V114 L0 130 Z" />
            <circle className="face" cx="0" cy="22" r="7" />
          </symbol>
          <symbol id={transformerId} viewBox="-85 -105 170 210">
            <path className="face" d="M-52 -8 L0 -38 L57 -5 L4 26 Z" />
            <path className="side" d="M-52 -8 L4 26 L4 78 L-52 45 Z" />
            <path className="face" d="M4 26 L57 -5 L57 47 L4 78 Z" />
            <path className="main" d="M-62 2 L-52 8 M-62 12 L-52 18 M-62 22 L-52 28 M-62 32 L-52 38 M58 5 L69 -1 M58 16 L69 10 M58 27 L69 21 M58 38 L69 32" />
            <path className="detail" d="M-68 -2 V40 M-62 2 V44 M69 -1 V36 M75 -5 V32" />
            <g className="main"><path d="M-28 -22 V-59 M0 -38 V-78 M29 -22 V-59" /><path d="M-36 -31 H-20 M-35 -39 H-21 M-34 -47 H-22 M-9 -49 H9 M-8 -58 H8 M-7 -67 H7 M21 -31 H37 M22 -39 H36 M23 -47 H35" /></g>
            <path className="face" d="M-45 -83 L14 -49 L42 -65 L-17 -99 Z" />
            <path className="detail" d="M-45 -83 V-70 L14 -36 V-49 M42 -65 V-53 L14 -36" />
            <path className="main" d="M-18 -64 L-4 -56 V-40 M-40 56 V69 M44 54 V67" />
          </symbol>
          <symbol id={breakerId} viewBox="-30 -75 60 150">
            <path className="main" d="M0 54 V15 M0 -5 V-45" />
            <path className="face" d="M-17 15 L0 5 L17 15 L0 25 Z" />
            <path className="side" d="M-17 15 L0 25 V43 L-17 33 Z" />
            <path className="face" d="M0 25 L17 15 V33 L0 43 Z" />
            <path className="main" d="M-14 -7 H14 M-12 -17 H12 M-10 -27 H10" />
          </symbol>
        </defs>

        <path className="ground" d="M300 360 L590 528 L300 696 L10 528 Z" opacity=".28" />
        <path className="ground" d="M35 680 L300 527 L565 680 M120 780 L385 627 M480 795 L145 602" opacity=".11" />

        <g aria-hidden="true">
          <path className="wire" d={MAIN_NETWORK_CONNECTION} data-network-connection="main" />
          <path className="flow" filter={`url(#${glowId})`} d={MAIN_NETWORK_CONNECTION}>
            <animate attributeName="stroke-dashoffset" from="0" to="-198" dur="2.4s" repeatCount="indefinite" />
          </path>
          {connectedPlantSlots.map((slot) => {
            const connectionPath = getNetworkConnectionPath(slot);
            const duration = 2.7 + (slot.phase % 5) * 0.13;
            return (
              <g key={`connection-${slot.x}-${slot.y}`}>
                <path
                  className="wire connected-wire"
                  d={connectionPath}
                  data-network-connection={`plant-${slot.x}-${slot.y}`}
                />
                <path className="flow connected-flow" filter={`url(#${glowId})`} d={connectionPath}>
                  <animate
                    attributeName="stroke-dashoffset"
                    from="0"
                    to="-198"
                    dur={`${duration}s`}
                    begin={`${-(slot.phase % 19) / 10}s`}
                    repeatCount="indefinite"
                  />
                </path>
              </g>
            );
          })}
        </g>

        <g aria-label="Usina solar principal" transform="translate(-300 0)">
          <path className="ground" d="M600 92 L812 214 L600 337 L388 214 Z" opacity=".7" />
          <g transform="translate(490 130) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-7 0 22;7 0 22;-7 0 22" dur="12s" repeatCount="indefinite" /></g></g>
          <g transform="translate(600 194) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-5 0 22;8 0 22;-5 0 22" dur="13s" repeatCount="indefinite" /></g></g>
          <g transform="translate(710 258) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-8 0 22;5 0 22;-8 0 22" dur="11s" repeatCount="indefinite" /></g></g>
          <g transform="translate(430 228) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-6 0 22;7 0 22;-6 0 22" dur="12.5s" repeatCount="indefinite" /></g></g>
          <g transform="translate(540 292) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-7 0 22;6 0 22;-7 0 22" dur="11.8s" repeatCount="indefinite" /></g></g>
          <g transform="translate(650 356) scale(.62)"><use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" /><g className="tracker-live"><use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" /><animateTransform attributeName="transform" type="rotate" values="-5 0 22;7 0 22;-5 0 22" dur="13.2s" repeatCount="indefinite" /></g></g>
        </g>

        <g
          aria-label="Subestação coletora"
          transform={`translate(${NETWORK_SUBSTATION_ANCHOR.x - 330} ${NETWORK_SUBSTATION_ANCHOR.y - 330}) scale(.55)`}
        >
          <path className="face" d="M600 476 L792 587 L600 698 L408 587 Z" />
          <path className="side" d="M408 587 L600 698 V712 L408 601 Z" />
          <path className="side" d="M600 698 L792 587 V601 L600 712 Z" />
          <path className="fence" d="M600 488 L774 588 L600 688 L426 588 Z" />
          <g className="detail" opacity=".5"><path d="M426 588 V545 M469 563 V520 M512 538 V495 M688 538 V495 M731 563 V520 M774 588 V545" /><path d="M442 598 V555 M486 623 V580 M530 648 V605 M670 648 V605 M714 623 V580 M758 598 V555" /></g>
          <g className="main"><path d="M494 558 V451 M706 558 V451" /><path d="M494 451 L706 573" /><path d="M494 469 L706 591" opacity=".45" /><path d="M519 466 L508 482 M560 490 L549 506 M601 514 L590 530 M642 538 L631 554 M683 562 L672 578" /></g>
          <g transform="translate(510 573) scale(.72)"><use className="equipment" href={`#${breakerId}`} x="-30" y="-75" width="60" height="150" /></g>
          <g transform="translate(690 573) scale(.72)"><use className="equipment" href={`#${breakerId}`} x="-30" y="-75" width="60" height="150" /></g>
          <path className="main" d="M510 523 L600 575 L690 523" />
          <path className="detail" d="M531 535 L540 522 M555 549 L564 536 M579 563 L588 550 M621 563 L612 550 M645 549 L636 536 M669 535 L660 522" />
          <g transform="translate(530 626) scale(.66)"><use className="equipment" href={`#${transformerId}`} x="-85" y="-105" width="170" height="210" /></g>
          <g transform="translate(650 661) scale(.66)"><use className="equipment" href={`#${transformerId}`} x="-85" y="-105" width="170" height="210" /></g>
          <g><path className="face" d="M676 603 L726 574 L766 597 L716 626 Z" /><path className="side" d="M676 603 L716 626 V664 L676 641 Z" /><path className="face" d="M716 626 L766 597 V635 L716 664 Z" /><path className="detail" d="M728 630 L750 617 V638 L728 651 Z M687 614 L706 625 V644 L687 633 Z" /></g>
        </g>

        {connectedPlantSlots.map((slot, index) => {
          const firstDuration = 11.4 + (slot.phase % 7) * 0.27;
          const secondDuration = 12.1 + (slot.phase % 5) * 0.31;
          const phaseOffset = -(slot.phase % 23) / 10;
          return (
            <g
              key={`plant-${slot.x}-${slot.y}`}
              data-connected-plant={`plant-${index + 1}`}
              aria-label={`Usina solar conectada ${index + 1}`}
              transform={`translate(${slot.x} ${slot.y}) scale(${slot.scale})`}
              opacity={slot.edge ? 0.76 : 0.86}
            >
              <path className="ground" d="M0 -110 L150 -24 L0 62 L-150 -24 Z" />
              <g transform="translate(-52 -55)">
                <use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" />
                <g className="tracker-live">
                  <use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" />
                  <animateTransform
                    attributeName="transform"
                    type="rotate"
                    values="-7 0 22;7 0 22;-7 0 22"
                    dur={`${firstDuration}s`}
                    begin={`${phaseOffset}s`}
                    repeatCount="indefinite"
                  />
                </g>
              </g>
              <g transform="translate(55 8)">
                <use className="equipment" href={`#${standId}`} x="-100" y="-20" width="200" height="150" />
                <g className="tracker-live">
                  <use className="equipment" href={`#${panelId}`} x="-100" y="-60" width="200" height="120" />
                  <animateTransform
                    attributeName="transform"
                    type="rotate"
                    values="-5 0 22;8 0 22;-5 0 22"
                    dur={`${secondDuration}s`}
                    begin={`${phaseOffset - 0.6}s`}
                    repeatCount="indefinite"
                  />
                </g>
              </g>
            </g>
          );
        })}
      </svg>

      <style>{`
        .solar-network-illustration {
          --ink: #26383c;
          --mid: #718185;
          --soft: #aab4b6;
          --face: #f4f6f5;
          --side: #d1d8d7;
          --energy: #18a86b;
          position: relative;
          display: block;
          width: 100%;
          max-width: none;
          margin: 0;
          overflow: visible;
          color: var(--ink);
          isolation: isolate;
          pointer-events: none;
        }
        .solar-network-illustration__canvas { display: block; width: 100%; height: auto; }
        .solar-network-illustration .main,
        .solar-network-illustration .detail,
        .solar-network-illustration .wire,
        .solar-network-illustration .fence,
        .solar-network-illustration .ground {
          fill: none;
          stroke-linecap: round;
          stroke-linejoin: round;
          vector-effect: non-scaling-stroke;
        }
        .solar-network-illustration .main { stroke: var(--ink); stroke-width: 2.2; }
        .solar-network-illustration .detail { stroke: var(--mid); stroke-width: 1.3; }
        .solar-network-illustration .ground { stroke: var(--soft); stroke-width: 1.2; stroke-dasharray: 5 6; }
        .solar-network-illustration .fence { stroke: var(--mid); stroke-width: 1.05; stroke-dasharray: 3 5; opacity: .48; }
        .solar-network-illustration .face { fill: var(--face); stroke: var(--ink); stroke-width: 1.8; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
        .solar-network-illustration .side { fill: var(--side); stroke: var(--ink); stroke-width: 1.8; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
        .solar-network-illustration .equipment { fill: var(--face); stroke: var(--ink); stroke-width: 1.8; stroke-linejoin: round; }
        .solar-network-illustration .wire { stroke: #637377; stroke-width: 1.45; }
        .solar-network-illustration .flow { fill: none; stroke: var(--energy); stroke-width: 1.8; stroke-dasharray: 22 176; stroke-linecap: round; vector-effect: non-scaling-stroke; }
      `}</style>
    </figure>
  );
}
