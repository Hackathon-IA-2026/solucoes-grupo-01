import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "~/lib/cn";

export type SectionNavItem = { id: string; title: string };

export function SectionNav({ items }: { items: SectionNavItem[] }) {
  const [activeId, setActiveId] = useState(items[0]?.id ?? "");
  const [expanded, setExpanded] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const programmaticTarget = useRef<string | null>(null);
  const navigationTimer = useRef<number | null>(null);
  const wheelAccumulator = useRef(0);
  const wheelResetTimer = useRef<number | null>(null);

  useEffect(() => {
    const targets = items
      .map((item) => document.getElementById(item.id))
      .filter((element): element is HTMLElement => element !== null);
    if (targets.length === 0) return;

    const pickActive = () => {
      // The section whose top edge is closest to one third of the viewport wins.
      const anchor = window.innerHeight / 3;
      let bestId = targets[0].id;
      let bestDistance = Number.POSITIVE_INFINITY;
      for (const target of targets) {
        const distance = Math.abs(target.getBoundingClientRect().top - anchor);
        if (distance < bestDistance) {
          bestDistance = distance;
          bestId = target.id;
        }
      }
      // While a click-driven smooth scroll is in flight, keep the clicked dot lit
      // until the page actually arrives, so the highlight does not flicker through
      // every section it passes over.
      if (programmaticTarget.current && programmaticTarget.current !== bestId) return;
      programmaticTarget.current = null;
      setActiveId(bestId);
    };

    pickActive();
    window.addEventListener("scroll", pickActive, { passive: true });
    window.addEventListener("resize", pickActive);
    return () => {
      window.removeEventListener("scroll", pickActive);
      window.removeEventListener("resize", pickActive);
    };
  }, [items]);

  useEffect(() => () => {
    if (navigationTimer.current) window.clearTimeout(navigationTimer.current);
    if (wheelResetTimer.current) window.clearTimeout(wheelResetTimer.current);
  }, []);

  useEffect(() => {
    if (!expanded) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!navRef.current?.contains(event.target as Node)) setExpanded(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded]);

  const goTo = useCallback((id: string) => {
    const target = document.getElementById(id);
    if (!target) return;
    if (navigationTimer.current) window.clearTimeout(navigationTimer.current);
    programmaticTarget.current = id;
    setActiveId(id);
    setExpanded(false);
    setHoveredId(null);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const headerBottom = document.querySelector<HTMLElement>("[data-app-header]")?.getBoundingClientRect().bottom ?? 0;
    const targetTop = window.scrollY + target.getBoundingClientRect().top - headerBottom;
    window.scrollTo({ top: Math.max(0, targetTop), behavior: reducedMotion ? "auto" : "smooth" });
    navigationTimer.current = window.setTimeout(() => {
      programmaticTarget.current = null;
    }, reducedMotion ? 0 : 1000);
  }, []);

  useEffect(() => {
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;

      const direction = event.deltaY > 0 ? 1 : -1;
      const currentIndex = items.findIndex((item) => item.id === activeId);
      const nextItem = items[currentIndex + direction];
      if (!nextItem) return;

      event.preventDefault();
      if (programmaticTarget.current) return;

      wheelAccumulator.current += event.deltaY;
      if (wheelResetTimer.current) window.clearTimeout(wheelResetTimer.current);
      wheelResetTimer.current = window.setTimeout(() => {
        wheelAccumulator.current = 0;
      }, 160);

      if (Math.abs(wheelAccumulator.current) < 24) return;
      wheelAccumulator.current = 0;
      goTo(nextItem.id);
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    return () => window.removeEventListener("wheel", onWheel);
  }, [activeId, goTo, items]);

  // The item that carries the visual emphasis: whatever is hovered, otherwise
  // the section currently on screen.
  const emphasisId = hoveredId ?? activeId;

  return (
    <nav
      ref={navRef}
      aria-label="Seções da exposição"
      data-section-nav=""
      data-expanded={expanded ? "true" : "false"}
      className="no-print fixed left-2 top-1/2 z-40 hidden -translate-y-1/2 lg:block"
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => { setExpanded(false); setHoveredId(null); }}
      onFocus={() => setExpanded(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setExpanded(false);
          setHoveredId(null);
        }
      }}
    >
      <ol className="flex flex-col gap-2">
        {items.map((item, index) => {
          const isActive = item.id === activeId;
          const isEmphasis = item.id === emphasisId;
          return (
            <li key={item.id} className="flex">
              <button
                type="button"
                onClick={() => goTo(item.id)}
                onMouseEnter={() => setHoveredId(item.id)}
                onFocus={() => setHoveredId(item.id)}
                onBlur={() => setHoveredId(null)}
                aria-current={isActive ? "true" : undefined}
                data-section-link={item.id}
                data-emphasis={isEmphasis ? "true" : "false"}
                title={expanded ? undefined : item.title}
                className={cn(
                  "group flex min-h-11 items-center gap-2 rounded-full border border-transparent bg-transparent text-left text-xs text-ink transition-[width,transform,background-color,color,box-shadow] duration-200 ease-out hover:bg-accent hover:text-white",
                  expanded ? "w-[16.5rem] px-3" : "w-11 justify-center px-0",
                  (isActive || isEmphasis) && "bg-accent text-white",
                  isEmphasis && "scale-[1.08] font-semibold shadow-[0_3px_9px_rgba(8,117,111,.3)]",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "num grid w-6 shrink-0 place-items-center text-xs transition-[font-size] duration-200 ease-out",
                    isEmphasis && "text-base",
                  )}
                >
                  {index + 1}
                </span>
                <span className={cn("min-w-0 truncate text-sm", expanded ? "block" : "sr-only")}>{item.title}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
