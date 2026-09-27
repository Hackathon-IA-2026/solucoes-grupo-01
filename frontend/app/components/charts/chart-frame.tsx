import { ChartBarIcon, TableIcon } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";
import { Panel } from "~/components/ui/panel";
import { StateBadge } from "~/components/evidence/evidence";
import type { EvidenceMetadata } from "~/domain/types";

export function ChartFrame({ title, description, evidence, children, table }: { title: string; description: string; evidence: EvidenceMetadata; children: ReactNode; table: ReactNode }) {
  return (
    <Panel title={title} description={description} action={<StateBadge state={evidence.state} />}>
      <ChartBody evidence={evidence} table={table}>{children}</ChartBody>
    </Panel>
  );
}

/**
 * The chart, its equivalent table and its provenance, without the surrounding
 * Panel. Use this to stack several charts inside one card.
 */
export function ChartBody({ evidence, children, table, showProvenance = true, switchView = false, chartClassName = "h-64" }: { evidence: EvidenceMetadata; children: ReactNode; table?: ReactNode; showProvenance?: boolean; switchView?: boolean; chartClassName?: string }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const hasTable = table !== undefined && table !== null;
  return (
    <>
      {switchView && hasTable ? (
        <>
          <div className="mb-1 flex justify-end">
            <button
              type="button"
              aria-label={view === "chart" ? "Mostrar tabela" : "Mostrar gráfico"}
              title={view === "chart" ? "Mostrar tabela" : "Mostrar gráfico"}
              onClick={() => setView((current) => current === "chart" ? "table" : "chart")}
              className="grid min-h-11 min-w-11 place-items-center rounded-md text-ink-soft transition-colors hover:bg-accent-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {view === "chart" ? <TableIcon size={18} aria-hidden="true" /> : <ChartBarIcon size={18} aria-hidden="true" />}
            </button>
          </div>
          {view === "chart" ? <div aria-hidden="true" className={`${chartClassName} min-w-0`}>{children}</div> : <div className="max-w-full">{table}</div>}
        </>
      ) : (
        <>
          <div aria-hidden={hasTable || undefined} className={`${chartClassName} min-w-0`}>{children}</div>
          {hasTable ? <details className="mt-4 border-t border-line pt-3">
            <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold text-accent">Ver dados em tabela</summary>
            <div className="max-w-full overflow-x-auto">{table}</div>
          </details> : null}
        </>
      )}
      {showProvenance ? <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-line pt-3 text-xs leading-5 text-ink-soft sm:grid-cols-2">
        <Provenance label="Unidade" value={evidence.unit} /><Provenance label="Período" value={evidence.period.label} />
        <Provenance label="Fonte" value={evidence.source} /><Provenance label="Versão" value={evidence.dataVersion} />
        <div className="sm:col-span-2"><Provenance label="Método" value={evidence.method} /></div>
      </dl> : null}
    </>
  );
}

/** A titled block inside a multi-chart card. */
export function ChartSlot({ title, description, evidence, children, showHeader = true, compactHeader = false, className = "" }: { title: string; description: string; evidence: EvidenceMetadata; children: ReactNode; showHeader?: boolean; compactHeader?: boolean; className?: string }) {
  return (
    <section className={`border-t border-line pt-4 first:border-t-0 first:pt-0 ${className}`}>
      {showHeader ? compactHeader ? (
        <h3 className="mb-2 text-sm font-semibold text-ink text-pretty">{title}</h3>
      ) : (
        <header className="mb-3 flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-semibold text-pretty">{title}</h3>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-soft">{description}</p>
          </div>
          <StateBadge state={evidence.state} />
        </header>
      ) : <h3 className="sr-only">{title}</h3>}
      {children}
    </section>
  );
}

/**
 * A titled block inside a shared card for content that is not a chart: metric
 * grids, the topology view, a table. Same separator rhythm as ChartSlot, but the
 * state badge is optional because the block may mix several states.
 */
export function CardSlot({ title, description, badge, children, showHeader = true }: { title: string; description?: string; badge?: ReactNode; children: ReactNode; showHeader?: boolean }) {
  return (
    <section className="border-t border-line pt-4 first:border-t-0 first:pt-0">
      {showHeader ? <header className="mb-3 flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-pretty">{title}</h3>
          {description ? <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-soft">{description}</p> : null}
        </div>
        {badge}
      </header> : <h3 className="sr-only">{title}</h3>}
      {children}
    </section>
  );
}

function Provenance({ label, value }: { label: string; value: string }) {
  return <div><dt className="inline font-semibold text-ink">{label}: </dt><dd className="inline">{value}</dd></div>;
}

export function DataTable({ caption, headers, rows, fitContainer = false }: { caption: string; headers: string[]; rows: (string | number | null)[][]; fitContainer?: boolean }) {
  const tableClass = fitContainer ? "w-full table-fixed border-collapse text-left text-sm" : "w-full min-w-[420px] border-collapse text-left text-sm";
  const cellClass = fitContainer ? "border-b border-line px-2 py-2 align-top break-words" : "border-b border-line px-3 py-2";
  return <table className={tableClass}><caption className="sr-only">{caption}</caption><thead><tr>{headers.map((header) => <th scope="col" className={`${cellClass} font-semibold`} key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td className={`${cellClass} border-line/70 num`} key={cellIndex}>{cell === null ? "Indisponível" : cell}</td>)}</tr>)}</tbody></table>;
}
