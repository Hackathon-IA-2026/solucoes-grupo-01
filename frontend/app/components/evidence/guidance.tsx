import { ArrowRightIcon, ChartLineIcon, InfoIcon, WarningIcon } from "@phosphor-icons/react";
import { Link } from "react-router";
import type { Guidance } from "~/domain/types";

const items = [
  ["Dado", "data", ChartLineIcon],
  ["Implicação", "implication", InfoIcon],
  ["Limitação", "limitation", WarningIcon],
] as const;

export function EvidenceGuidance({ guidance }: { guidance: Guidance }) {
  return (
    <section aria-labelledby="guidance-title" className="rounded-xl border-2 border-ink bg-ink text-white">
      <div className="border-b border-white/20 px-5 py-4"><h2 id="guidance-title" className="text-lg font-semibold">Orientação para a decisão</h2></div>
      <div className="grid md:grid-cols-3">
        {items.map(([label, key, Icon]) => (
          <article key={key} className="border-b border-white/15 p-5 md:border-b-0 md:border-r last:md:border-r-0">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-accent-soft"><Icon aria-hidden="true" />{label}</h3>
            <p className="mt-3 text-sm leading-6 text-white/90">{guidance[key]}</p>
          </article>
        ))}
      </div>
      <div className="flex flex-col gap-3 bg-white/5 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div><h3 className="text-sm font-semibold text-accent-soft">Próxima ação</h3><p className="mt-1 text-sm text-white/90">{guidance.nextAction}</p></div>
        {guidance.nextHref ? <Link className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-ink hover:bg-accent-soft" to={guidance.nextHref}>Continuar <ArrowRightIcon aria-hidden="true" /></Link> : null}
      </div>
    </section>
  );
}
