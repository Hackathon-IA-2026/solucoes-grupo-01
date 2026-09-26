import type { DataQuality } from "~/domain/types";
import { Panel } from "~/components/ui/panel";
import { EvidenceMetric } from "./evidence";

export function DataQualityPanel({ quality }: { quality: DataQuality }) {
  return (
    <Panel title="Qualidade e materialização" description="A falha de uma fonte degrada apenas a capacidade que depende dela.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <EvidenceMetric label="Cobertura" evidence={quality.coverage} />
        <EvidenceMetric label="Atraso" evidence={quality.delay} />
        <EvidenceMetric label="Nulos" evidence={quality.nullRate} />
        <EvidenceMetric label="Duplicatas" evidence={quality.duplicates} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm text-ink-soft sm:grid-cols-2">
        <Item label="Granularidade" value={quality.granularity} /><Item label="Versão" value={quality.dataVersion} />
        <Item label="Esquema" value={quality.schemaStatus} /><Item label="Mudanças de esquema" value={quality.schemaChanges} />
        <Item label="Última materialização" value={quality.lastMaterialization} /><Item label="Execução do modelo" value={quality.modelExecution} />
      </dl>
    </Panel>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-canvas p-3"><dt className="font-semibold text-ink">{label}</dt><dd className="mt-1">{value}</dd></div>;
}
