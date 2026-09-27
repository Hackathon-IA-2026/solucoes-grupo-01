import type { DataQuality } from "~/domain/types";
import { Panel } from "~/components/ui/panel";
import { EvidenceMetric } from "./evidence";

export function DataQualityPanel({ quality }: { quality: DataQuality }) {
  return (
    <Panel title="Qualidade e materialização" description="A falha de uma fonte degrada apenas a capacidade que depende dela.">
      <DataQualityBody quality={quality} />
    </Panel>
  );
}

/** The quality metrics without their own Panel, for stacking inside a shared card. */
export function DataQualityBody({ quality, showState = true }: { quality: DataQuality; showState?: boolean }) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceMetric label="Cobertura" evidence={quality.coverage} showState={showState} />
        <EvidenceMetric label="Atraso" evidence={quality.delay} showState={showState} />
        <EvidenceMetric label="Nulos" evidence={quality.nullRate} showState={showState} />
        <EvidenceMetric label="Duplicatas" evidence={quality.duplicates} showState={showState} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm text-ink-soft sm:grid-cols-2">
        <Item label="Granularidade" value={quality.granularity} /><Item label="Versão" value={quality.dataVersion} />
        <Item label="Esquema" value={quality.schemaStatus} /><Item label="Mudanças de esquema" value={quality.schemaChanges} />
        <Item label="Última materialização" value={quality.lastMaterialization} /><Item label="Execução do modelo" value={quality.modelExecution} />
      </dl>
    </>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-canvas p-3"><dt className="font-semibold text-ink">{label}</dt><dd className="mt-1">{value}</dd></div>;
}
