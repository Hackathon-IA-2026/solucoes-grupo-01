import type { ReactNode } from "react";
import { Panel } from "~/components/ui/panel";
import { StateBadge } from "~/components/evidence/evidence";
import type { EvidenceMetadata } from "~/domain/types";

export function ChartFrame({ title, description, evidence, children, table }: { title: string; description: string; evidence: EvidenceMetadata; children: ReactNode; table: ReactNode }) {
  return (
    <Panel title={title} description={description} action={<StateBadge state={evidence.state} />}>
      <div aria-hidden="true" className="h-64 min-w-0">{children}</div>
      <details className="mt-4 border-t border-line pt-3">
        <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold text-accent">Ver dados em tabela</summary>
        <div className="max-w-full overflow-x-auto">{table}</div>
      </details>
      <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-line pt-3 text-xs leading-5 text-ink-soft sm:grid-cols-2">
        <Provenance label="Unidade" value={evidence.unit} /><Provenance label="Período" value={evidence.period.label} />
        <Provenance label="Fonte" value={evidence.source} /><Provenance label="Versão" value={evidence.dataVersion} />
        <div className="sm:col-span-2"><Provenance label="Método" value={evidence.method} /></div>
      </dl>
    </Panel>
  );
}

function Provenance({ label, value }: { label: string; value: string }) {
  return <div><dt className="inline font-semibold text-ink">{label}: </dt><dd className="inline">{value}</dd></div>;
}

export function DataTable({ caption, headers, rows }: { caption: string; headers: string[]; rows: (string | number | null)[][] }) {
  return <table className="w-full min-w-[420px] border-collapse text-left text-sm"><caption className="sr-only">{caption}</caption><thead><tr>{headers.map((header) => <th scope="col" className="border-b border-line px-3 py-2 font-semibold" key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td className="border-b border-line/70 px-3 py-2 num" key={cellIndex}>{cell === null ? "Indisponível" : cell}</td>)}</tr>)}</tbody></table>;
}
