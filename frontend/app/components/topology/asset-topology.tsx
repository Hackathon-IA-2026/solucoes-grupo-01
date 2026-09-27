import { useMemo, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow, type Node, type NodeProps } from "@xyflow/react";
import { BuildingsIcon, FactoryIcon, LightningIcon, NetworkIcon } from "@phosphor-icons/react";
import type { Asset } from "~/domain/types";
import { Panel } from "~/components/ui/panel";

/** A plant that shares the selected plant's ONS group and/or connection point. */
export type PlantTopologyPlant = {
  id: string;
  name: string;
  technology?: "wind" | "solar" | string;
  groupId?: string | null;
};

/**
 * Facts the topology needs to describe a single plant: the ONS group it belongs
 * to and the plants that accompany it. Both lists include the selected plant.
 */
export type PlantTopologyContext = {
  onsGroupId?: string | null;
  onsGroupName?: string | null;
  /** Every plant connected to the selected plant's connection point. */
  pointPlants?: PlantTopologyPlant[];
  /** Every plant that belongs to the selected plant's ONS group. */
  groupPlants?: PlantTopologyPlant[];
};

export type TopologyPeerScope = "group" | "point" | "both";
export type TopologyPeer = PlantTopologyPlant & { scope: TopologyPeerScope };

export type PlantTopologyPeers = {
  peers: TopologyPeer[];
  /** Same ONS group peers, used for reconciliation. */
  groupPeerCount: number;
  /** Same connection point peers, used for systemic pressure. */
  pointPeerCount: number;
  /** Distinct plants across both scopes, so nothing is counted twice. */
  uniquePeerCount: number;
};

function dedupeById(plants: PlantTopologyPlant[]): PlantTopologyPlant[] {
  const seen = new Set<string>();
  const result: PlantTopologyPlant[] = [];
  for (const plant of plants) {
    if (!plant.id || seen.has(plant.id)) continue;
    seen.add(plant.id);
    result.push(plant);
  }
  return result;
}

/**
 * Splits the plants that accompany the selected one into the reconciliation
 * scope (same ONS group) and the systemic-pressure scope (same connection
 * point). A plant present in both scopes appears exactly once, so the derived
 * totals never double count it.
 */
function derivePlantTopologyPeers(selectedId: string, context?: PlantTopologyContext): PlantTopologyPeers {
  const groupPeers = dedupeById((context?.groupPlants ?? []).filter((plant) => plant.id !== selectedId));
  const pointPeers = dedupeById((context?.pointPlants ?? []).filter((plant) => plant.id !== selectedId));
  const groupIds = new Set(groupPeers.map((plant) => plant.id));
  const pointIds = new Set(pointPeers.map((plant) => plant.id));
  const peers: TopologyPeer[] = [];
  for (const plant of pointPeers) peers.push({ ...plant, scope: groupIds.has(plant.id) ? "both" : "point" });
  for (const plant of groupPeers) if (!pointIds.has(plant.id)) peers.push({ ...plant, scope: "group" });
  return {
    peers,
    groupPeerCount: groupPeers.length,
    pointPeerCount: pointPeers.length,
    uniquePeerCount: peers.length,
  };
}

function peerDetail(peer: TopologyPeer) {
  if (peer.scope === "both") return "Mesmo conjunto e mesmo ponto";
  if (peer.scope === "group") return "Mesmo conjunto (reconciliação)";
  return "Mesmo ponto (pressão sistêmica)";
}

function AssetNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-48 rounded-xl border-2 border-accent bg-white p-3 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold"><LightningIcon aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs text-ink-soft">{data.detail}</p><Handle type="source" position={Position.Bottom} className="opacity-0" /></div>;
}
function GroupNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-48 rounded-xl border border-accent bg-accent-soft p-3"><Handle type="target" position={Position.Top} className="opacity-0" /><div className="flex items-center gap-2 text-sm font-semibold"><BuildingsIcon aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs text-ink-soft">{data.detail}</p><Handle type="source" position={Position.Bottom} className="opacity-0" /></div>;
}
function PointNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-48 rounded-xl border border-ink bg-ink p-3 text-white"><Handle type="target" position={Position.Top} className="opacity-0" /><div className="flex items-center gap-2 text-sm font-semibold"><NetworkIcon aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs text-white/80">{data.detail}</p><Handle type="source" position={Position.Bottom} className="opacity-0" /></div>;
}
function EntityNode({ data }: NodeProps<Node<{ label: string; detail: string }>>) {
  return <div className="w-44 rounded-lg border border-line-strong bg-canvas p-3"><Handle type="target" position={Position.Top} className="opacity-0" /><div className="flex items-center gap-2 text-xs font-semibold"><FactoryIcon className="shrink-0" aria-hidden="true" />{data.label}</div><p className="mt-1 text-xs leading-4 text-ink-soft">{data.detail}</p></div>;
}
const nodeTypes = { asset: AssetNode, group: GroupNode, point: PointNode, entity: EntityNode };

export function AssetTopology({ asset, context }: { asset: Asset; context?: PlantTopologyContext }) {
  return (
    <Panel title="Posição da usina no ponto de conexão" description="A ilustração mostra a usina, o conjunto ONS e o ponto de conexão, sem dados operacionais.">
      <AssetTopologyBody asset={asset} context={context} />
    </Panel>
  );
}

/** The topology view without its own Panel, for stacking inside a shared card. */
export function AssetTopologyBody({ asset, context }: { asset: Asset; context?: PlantTopologyContext }) {
  const [listView, setListView] = useState(false);
  const { peers, groupPeerCount, pointPeerCount, uniquePeerCount } = useMemo(
    () => derivePlantTopologyPeers(asset.id, context),
    [asset.id, context],
  );
  const groupLabel = context?.onsGroupName ?? context?.onsGroupId ?? null;
  const hasGroup = Boolean(context && (groupLabel || peers.length > 0));
  const anonymousCount = context ? 0 : asset.anonymousEntities;
  const nodeCount = peers.length + anonymousCount;
  const reconciliationPeers = peers.filter((peer) => peer.scope !== "point");
  const systemicPeers = peers.filter((peer) => peer.scope !== "group");
  const nodes = useMemo<Node[]>(() => {
    const layout: Node[] = [
      { id: "asset", type: "asset", position: { x: 190, y: 0 }, data: { label: asset.name, detail: `${asset.technology} · ${asset.location}` } },
    ];
    if (hasGroup) {
      layout.push({ id: "group", type: "group", position: { x: 190, y: 110 }, data: { label: groupLabel ?? "Conjunto ONS", detail: "Conjunto ao qual a usina pertence" } });
    }
    const pointY = hasGroup ? 220 : 110;
    layout.push({ id: "point", type: "point", position: { x: 190, y: pointY }, data: { label: asset.connectionPoint, detail: "Ponto de conexão usado nesta análise" } });
    for (let index = 0; index < nodeCount; index += 1) {
      const peer = peers[index];
      layout.push({
        id: `peer-${index}`,
        type: "entity",
        position: { x: (index % 3) * 210, y: pointY + 135 + Math.floor(index / 3) * 105 },
        data: {
          label: peer ? peer.name : `Usina no ponto ${index + 1}`,
          detail: peer ? peerDetail(peer) : "Sem identidade exibida",
        },
      });
    }
    return layout;
  }, [asset, groupLabel, hasGroup, nodeCount, peers]);
  const edges = useMemo(() => {
    const layout = hasGroup
      ? [
          { id: "asset-group", source: "asset", target: "group", style: { stroke: "#08756f", strokeWidth: 2 } },
          { id: "group-point", source: "group", target: "point", style: { stroke: "#08756f", strokeWidth: 2 } },
        ]
      : [{ id: "asset-point", source: "asset", target: "point", style: { stroke: "#08756f", strokeWidth: 2 } }];
    return [
      ...layout,
      ...Array.from({ length: nodeCount }, (_, index) => ({ id: `point-${index}`, source: "point", target: `peer-${index}`, style: { stroke: "#7b918d", strokeDasharray: "5 5" } })),
    ];
  }, [hasGroup, nodeCount]);
  return (
    <>
      <div className="mb-3 hidden justify-end md:flex"><button className="min-h-11 rounded-lg border border-line px-3 text-sm font-semibold hover:bg-accent-soft" onClick={() => setListView((value) => !value)} aria-pressed={listView}>{listView ? "Ver topologia" : "Ver como lista"}</button></div>
      <div className={listView ? "hidden" : "hidden h-[430px] overflow-hidden rounded-lg border border-line bg-white md:block"} aria-hidden={listView}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesFocusable={false} edgesFocusable={false} elementsSelectable={false} proOptions={{ hideAttribution: true }} nodesDraggable={false} nodesConnectable={false} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.5} maxZoom={1.4} zoomOnScroll={false}><Background color="#d7ddd8" gap={18} /><Controls position="top-right" showInteractive={false} /></ReactFlow>
      </div>
      <div data-topology-list className={listView ? "block" : "block md:hidden"}>
        <ul className="space-y-2 text-sm">
          <li className="rounded-lg bg-accent-soft p-3"><strong>{asset.name}</strong><br />{asset.technology} · {asset.location}</li>
          {hasGroup ? <li className="rounded-lg border border-accent bg-white p-3"><strong>{groupLabel ?? "Conjunto ONS"}</strong><br />Conjunto ao qual a usina pertence</li> : null}
          <li className="rounded-lg bg-ink p-3 text-white"><strong>{asset.connectionPoint}</strong><br />Ponto de conexão usado nesta análise</li>
          {Array.from({ length: anonymousCount }, (_, index) => <li key={`anonymous-${index}`} className="rounded-lg bg-canvas p-3"><strong>Usina no ponto {index + 1}</strong><br />Sem identidade exibida</li>)}
        </ul>
        {peers.length ? (
          <div className="mt-3 space-y-2 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Reconciliação no conjunto ({groupPeerCount})</p>
            <ul className="space-y-2">{reconciliationPeers.map((peer) => <li key={`group-${peer.id}`} className="rounded-lg bg-canvas p-3"><strong>{peer.name}</strong><br />{peerDetail(peer)}</li>)}</ul>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Pressão sistêmica no ponto ({pointPeerCount})</p>
            <ul className="space-y-2">{systemicPeers.map((peer) => <li key={`point-${peer.id}`} className="rounded-lg bg-canvas p-3"><strong>{peer.name}</strong><br />{peerDetail(peer)}</li>)}</ul>
            <p className="text-xs leading-5 text-ink-soft">{uniquePeerCount} usinas únicas somando conjunto e ponto, sem dupla contagem.</p>
          </div>
        ) : null}
      </div>
      <p className="mt-4 rounded-lg bg-canvas p-3 text-xs leading-5 text-ink-soft">O diagrama mostra a usina selecionada, o conjunto ONS ao qual ela pertence e o ponto de conexão, além das usinas que compartilham o conjunto ou o ponto. Ele não informa capacidade disponível, direção do fluxo nem causa elétrica dos cortes.</p>
    </>
  );
}
