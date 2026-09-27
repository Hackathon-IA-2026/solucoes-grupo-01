import { CaretDownIcon, DatabaseIcon } from "@phosphor-icons/react";
import type { EvidenceState, EvidenceValue } from "~/domain/types";
import { formatEvidence } from "~/lib/format";
import { cn } from "~/lib/cn";

const stateStyles: Record<EvidenceState, string> = {
  medido: "border-emerald-700/30 bg-emerald-50 text-emerald-900",
  calculado: "border-accent/30 bg-accent-soft text-ink",
  previsto: "border-blue-700/30 bg-blue-50 text-blue-900",
  simulado: "border-warning/30 bg-amber-50 text-amber-900",
  "informado pelo cliente": "border-violet-700/30 bg-violet-50 text-violet-900",
};

export function StateBadge({ state }: { state: EvidenceState }) {
  return <span className={cn("inline-flex rounded-md border px-2 py-1 text-xs font-semibold", stateStyles[state])}>{state}</span>;
}

export function EvidenceMetric({ label, evidence, emphasis = false, showState = true }: { label: string; evidence: EvidenceValue; emphasis?: boolean; showState?: boolean }) {
  return (
    <article className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink-soft">{label}</p>
        {showState ? <StateBadge state={evidence.state} /> : null}
      </div>
      <p className={cn("num mt-3 break-words font-semibold", emphasis ? "text-3xl" : "text-2xl")}>
        {formatEvidence(evidence.value, evidence.unit)}
      </p>
      {evidence.value === null && evidence.unavailableReason ? <p className="mt-2 text-sm text-danger">{evidence.unavailableReason}</p> : null}
      <details className="group mt-4 border-t border-line pt-3 text-sm">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 font-semibold text-accent">
          <DatabaseIcon aria-hidden="true" /> Caminho deste número <CaretDownIcon className="ml-auto transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <dl className="mt-2 grid gap-2 text-ink-soft sm:grid-cols-2">
          <Detail label="Período" value={evidence.period.label} />
          <Detail label="Fonte" value={evidence.source} />
          <Detail label="Versão" value={evidence.dataVersion} />
          <Detail label="Método" value={evidence.method} wide />
        </dl>
      </details>
    </article>
  );
}

function Detail({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return <div className={cn("min-w-0", wide && "sm:col-span-2")}><dt className="text-xs font-semibold uppercase tracking-wide">{label}</dt><dd className="mt-1 break-words text-sm">{value}</dd></div>;
}
