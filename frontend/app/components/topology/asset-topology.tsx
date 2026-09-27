import { useMemo, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow, type Node, type NodeProps } from "@xyflow/react";
import { FactoryIcon, LightningIcon, NetworkIcon } from "@phosphor-icons/react";
import type { Asset } from "~/domain/types";
import { Panel } from "~/components/ui/panel";

function AssetNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-48 rounded-xl border-2 border-accent bg-white p-3 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold"><LightningIcon aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs text-ink-soft">{data.detail}</p><Handle type="source" position={Position.Bottom} className="opacity-0" /></div>;
}
function PointNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-48 rounded-xl border border-ink bg-ink p-3 text-white"><Handle type="target" position={Position.Top} className="opacity-0" /><div className="flex items-center gap-2 text-sm font-semibold"><NetworkIcon aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs text-white/80">{data.detail}</p><Handle type="source" position={Position.Bottom} className="opacity-0" /></div>;
}
function EntityNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-44 rounded-lg border border-line-strong bg-canvas p-3"><Handle type="target" position={Position.Top} className="opacity-0" /><div className="flex items-center gap-2 text-xs font-semibold"><FactoryIcon className="shrink-0" aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs leading-4 text-ink-soft">{data.detail}</p></div>;
}
const nodeTypes = { asset: AssetNode, point: PointNode, entity: EntityNode };

export function AssetTopology({ asset }: { asset: Asset }) {
  return (
    <Panel title="Posição cadastral no ponto" description="A ilustração mostra somente associações cadastrais anonimizadas.">
      <AssetTopologyBody asset={asset} />
    </Panel>
  );
}

/** The topology view without its own Panel, for stacking inside a shared card. */
export function AssetTopologyBody({ asset }: { asset: Asset }) {
  const [listView, setListView] = useState(false);
  const nodes = useMemo<Node[]>(() => [
    { id: "asset", type: "asset", position: { x: 190, y: 0 }, data: { label: asset.name, detail: asset.technology } },
    { id: "point", type: "point", position: { x: 190, y: 110 }, data: { label: asset.connectionPoint, detail: "Ponto usado nesta análise" } },
    ...Array.from({ length: asset.anonymousEntities }, (_, index) => ({ id: `entity-${index}`, type: "entity", position: { x: (index % 3) * 210, y: 245 + Math.floor(index / 3) * 105 }, data: { label: `Outra usina ou conjunto ${index + 1}`, detail: "Identidade e dados operacionais não exibidos" } })),
  ], [asset]);
  const edges = useMemo(() => [
    { id: "asset-point", source: "asset", target: "point", style: { stroke: "#08756f", strokeWidth: 2 } },
    ...Array.from({ length: asset.anonymousEntities }, (_, index) => ({ id: `point-${index}`, source: "point", target: `entity-${index}`, style: { stroke: "#7b918d", strokeDasharray: "5 5" } })),
  ], [asset]);
  return (
    <>
      <div className="mb-3 hidden justify-end md:flex"><button className="min-h-11 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-accent-soft" onClick={() => setListView((value) => !value)} aria-pressed={listView}>{listView ? "Ver topologia" : "Ver como lista"}</button></div>
      <div className={listView ? "hidden" : "hidden h-[430px] overflow-hidden rounded-lg border border-line bg-white md:block"} aria-hidden={listView}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesFocusable={false} edgesFocusable={false} elementsSelectable={false} proOptions={{ hideAttribution: true }} nodesDraggable={false} nodesConnectable={false} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.5} maxZoom={1.4} zoomOnScroll={false}><Background color="#d7ddd8" gap={18} /><Controls position="top-right" showInteractive={false} /></ReactFlow>
      </div>
      <div data-topology-list className={listView ? "block" : "block md:hidden"}>
        <ul className="space-y-2 text-sm"><li className="rounded-lg bg-accent-soft p-3"><strong>{asset.name}</strong><br />{asset.technology}</li><li className="rounded-lg bg-ink p-3 text-white"><strong>{asset.connectionPoint}</strong><br />Ponto usado nesta análise</li>{Array.from({ length: asset.anonymousEntities }, (_, index) => <li key={index} className="rounded-lg bg-canvas p-3"><strong>Outra usina ou conjunto {index + 1}</strong><br />Identidade e dados operacionais não exibidos</li>)}</ul>
      </div>
      <p className="mt-4 rounded-lg bg-canvas p-3 text-xs leading-5 text-ink-soft">O diagrama mostra quais usinas ou conjuntos aparecem ligados ao mesmo ponto nos dados do ONS. Ele não informa capacidade disponível, direção do fluxo nem causa elétrica dos cortes.</p>
    </>
  );
}
