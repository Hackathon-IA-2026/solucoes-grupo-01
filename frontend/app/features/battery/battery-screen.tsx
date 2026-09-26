import { useState, type FormEvent } from "react";
import { BatteryChargingIcon, CheckCircleIcon, WarningIcon } from "@phosphor-icons/react";
import { AssetContext } from "~/components/layout/asset-context";
import { DecisionWorkspace } from "~/components/layout/decision-workspace";
import { EvidenceMetric } from "~/components/evidence/evidence";
import { EvidenceGuidance } from "~/components/evidence/guidance";
import { CapabilityUnavailable } from "~/components/evidence/capability-unavailable";
import { BatterySensitivityChart } from "~/components/charts/decision-charts";
import { Button } from "~/components/ui/button";
import { Panel } from "~/components/ui/panel";
import { batteryGuidance } from "~/domain/fixtures";
import { defaultResidualProfile, requestBatteryScenario } from "~/domain/mock-api";
import type { BatteryMode, BatteryScenario, BatteryScenarioRequest, EvidenceValue } from "~/domain/types";
import { useAnalysis } from "~/state/use-analysis";
import { cn } from "~/lib/cn";

const premiseLabels: Record<string, string> = {
  power: "Potência (MW)", capacity: "Capacidade (MWh)", dischargeDuration: "Duração de descarga (horas)", efficiency: "Eficiência (%)", price: "Preço parametrizado (R$/MWh)",
  availability: "Disponibilidade (%)", degradation: "Degradação anual (%/ano)", cycles: "Ciclos anuais", connectionLimit: "Limite de conexão (MW)",
  capex: "CAPEX total (R$)", projectLife: "Horizonte econômico (anos)", initialSoc: "SOC inicial (%)", remainingLife: "Vida útil remanescente (anos)",
};
const premiseGroups = [
  { title: "Configuração técnica", keys: ["power", "capacity", "dischargeDuration", "efficiency", "availability", "degradation", "cycles"] },
  { title: "Premissas econômicas", keys: ["price", "capex", "projectLife", "remainingLife"] },
  { title: "Operação e conexão", keys: ["connectionLimit", "initialSoc"] },
];

export function BatteryScreen() {
  const [mode, setMode] = useState<BatteryMode>("new");
  const [scenario, setScenario] = useState<BatteryScenario | null>(null);
  const [scenarioKey, setScenarioKey] = useState<string | null>(null);
  const [unsupportedKey, setUnsupportedKey] = useState<string | null>(null);
  const { state, recordBatterySelection } = useAnalysis();
  const recordedDecision = state.decision?.assetId === state.assetId ? state.decision : null;
  const residualProfileId = recordedDecision?.residualProfileId ?? defaultResidualProfile(state.assetId);
  const analysisKey = `${state.assetId}:${residualProfileId}:${mode}:${state.selectionRevision}`;
  const template = requestBatteryScenario(state.assetId, residualProfileId, mode);
  const visibleScenario = scenarioKey === analysisKey ? scenario : null;
  const unsupported = unsupportedKey === analysisKey;
  const recorded = state.batterySelection?.assetId === state.assetId && state.batterySelection.scenarioId === visibleScenario?.id;
  const chooseMode = (next: BatteryMode) => { setMode(next); };
  const evaluate = (request: BatteryScenarioRequest) => {
    const response = requestBatteryScenario(state.assetId, residualProfileId, mode, request);
    setScenario(response);
    setScenarioKey(response ? analysisKey : null);
    setUnsupportedKey(response ? null : analysisKey);
  };
  const record = () => {
    if (!visibleScenario) return;
    recordBatterySelection({ assetId: state.assetId, scenarioId: visibleScenario.id, residualProfileId, mode: visibleScenario.mode, recordedAt: new Date().toISOString() });
  };

  return <DecisionWorkspace title="Bateria sobre a perda residual" description="A manutenção reduz a perda de oportunidade associada à indisponibilidade. A bateria é avaliada sobre o curtailment que permanece depois dessas janelas." status="Triagem econômica preliminar, despacho ainda não validado" context={<AssetContext />}>
    {!recordedDecision ? <aside className="rounded-lg border border-warning/40 bg-amber-50 p-4 text-sm text-amber-950"><strong>Perfil residual de demonstração.</strong> Nenhuma janela foi registrada para este ativo na sessão. A triagem usa o perfil-base simulado {residualProfileId}.</aside> : <aside className="rounded-lg border border-accent/30 bg-accent-soft p-4 text-sm"><strong>Decisão herdada.</strong> A triagem usa o perfil {residualProfileId}, vinculado à janela {recordedDecision.selectedWindowId}.</aside>}
    <Panel title="Qual pergunta você quer responder?">
      <div className="grid gap-3 sm:grid-cols-2"><ModeButton active={mode === "new"} onClick={() => chooseMode("new")} title="Quero avaliar uma bateria nova" text="Informe CAPEX, horizonte e configuração técnica da candidata." /><ModeButton active={mode === "existing"} onClick={() => chooseMode("existing")} title="Já possuo uma bateria" text="Informe SOC, vida remanescente, fronteira e restrições da instalação." /></div>
    </Panel>
    {template ? <BatteryScenarioForm key={`${state.assetId}-${residualProfileId}-${mode}`} template={template} onSubmit={evaluate} /> : <CapabilityUnavailable title="Pacote BESS indisponível">Não existe uma configuração materializada para este ativo, perfil residual e modo.</CapabilityUnavailable>}
    {unsupported ? <CapabilityUnavailable title="Configuração ainda não materializada">A API demonstrativa não possui um resultado para os parâmetros alterados. Nenhum cenário anterior foi reutilizado.</CapabilityUnavailable> : null}
    {visibleScenario ? <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><EvidenceMetric label="Curtailment residual" evidence={visibleScenario.residualEnergy} /><EvidenceMetric label="Energia potencialmente absorvível" evidence={visibleScenario.absorbableEnergy} /><EvidenceMetric label="Custo anualizado" evidence={visibleScenario.annualizedCost} /><EvidenceMetric label="Receita parametrizada" evidence={visibleScenario.parameterizedBenefit} /><EvidenceMetric label="Lacuna econômica" evidence={visibleScenario.economicGap} emphasis /></div>
      <BatterySensitivityChart scenario={visibleScenario} />
      <Panel title="Dados necessários para estudo detalhado" description="Ausência não significa zero. Cada item abaixo impede despacho ou arbitragem validados.">
        <ul className="grid gap-2 sm:grid-cols-2">{visibleScenario.missingInputs.map((item) => <li key={item} className="flex items-start gap-2 rounded-lg bg-canvas p-3 text-sm"><WarningIcon className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />{item}</li>)}</ul>
      </Panel>
      <Panel title="Conclusão da triagem"><div className="flex items-start gap-3"><BatteryChargingIcon className="mt-1 shrink-0 text-accent" size={28} aria-hidden="true" /><div><p className="font-semibold">A configuração merece revisão antes de um estudo detalhado.</p><p className="mt-2 text-sm leading-6 text-ink-soft">O cenário apresenta lacuna econômica e não contém os dados necessários para validar operação. Não há promessa de corte evitado, energia recuperada, arbitragem ou retorno.</p><Button className="mt-4" variant="primary" onClick={record}>{recorded ? <><CheckCircleIcon aria-hidden="true" />Triagem registrada</> : "Registrar triagem no relatório"}</Button></div></div></Panel>
    </> : <Panel title="Triagem aguardando avaliação" description="Revise os parâmetros técnicos e econômicos e solicite a resposta materializada. O relatório permanece sem cenário BESS até o registro explícito." />}
    <EvidenceGuidance guidance={batteryGuidance} />
  </DecisionWorkspace>;
}

function BatteryScenarioForm({ template, onSubmit }: { template: BatteryScenario; onSubmit: (request: BatteryScenarioRequest) => void }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const premises = Object.fromEntries(Object.keys(template.request.premises).map((key) => {
      const raw = String(form.get(key) ?? "").trim();
      return [key, raw === "" ? null : Number(raw)];
    }));
    onSubmit({ premises, operationalRestrictions: String(form.get("operationalRestrictions") ?? ""), meterBoundary: String(form.get("meterBoundary") ?? ""), hourlyPriceSource: String(form.get("hourlyPriceSource") ?? "") });
  };
  return <Panel title={template.mode === "new" ? "Parâmetros da bateria nova" : "Parâmetros da bateria existente"} description="O backend retorna somente pacotes fechados. Alterações sem pacote correspondente geram um estado indisponível, sem cálculo no navegador.">
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
      {premiseGroups.map((group) => <fieldset key={group.title} className="grid gap-4 rounded-lg border border-line p-4 sm:col-span-2 sm:grid-cols-2"><legend className="px-2 text-sm font-semibold text-ink">{group.title}</legend>{group.keys.flatMap((key) => template.premises[key] ? [<NumericField key={key} name={key} evidence={template.premises[key]} />] : [])}</fieldset>)}
      <fieldset className="grid gap-4 rounded-lg border border-line p-4 sm:col-span-2 sm:grid-cols-2"><legend className="px-2 text-sm font-semibold text-ink">Restrições, medição e preço</legend><TextField name="operationalRestrictions" label="Restrições operacionais" value={template.request.operationalRestrictions} /><TextField name="meterBoundary" label="Fronteira de medição" value={template.request.meterBoundary} /><div className="sm:col-span-2"><TextField name="hourlyPriceSource" label="Preço horário ou fonte autorizada" value={template.request.hourlyPriceSource} /></div></fieldset>
      <div className="sm:col-span-2"><Button type="submit" variant="primary">Avaliar configuração</Button></div>
    </form>
  </Panel>;
}

function NumericField({ name, evidence }: { name: string; evidence: EvidenceValue }) {
  return <label className={cn("text-sm font-semibold", name === "projectLife" && "sm:col-span-2")}>{premiseLabels[name] ?? name}{evidence.value === null ? " (opcional)" : ""}<input name={name} type="number" step="any" placeholder={evidence.value === null ? "Não informado" : undefined} defaultValue={evidence.value ?? ""} className="mt-2 min-h-11 w-full rounded-lg border-2 border-line-strong bg-white px-3 py-2 text-sm" /><details className="mt-1 text-xs font-normal leading-5 text-ink-soft"><summary className="flex min-h-11 cursor-pointer items-center py-2 font-semibold text-accent">Procedência: {evidence.state}</summary><p>Fonte: {evidence.source}. Método: {evidence.method} Período: {evidence.period.label}. Versão: {evidence.dataVersion}.{evidence.unavailableReason ? ` ${evidence.unavailableReason}.` : ""}</p></details></label>;
}

function TextField({ name, label, value }: { name: string; label: string; value: string }) {
  return <label className="text-sm font-semibold">{label}<textarea name={name} rows={2} defaultValue={value} className="mt-2 min-h-16 w-full resize-y rounded-lg border-2 border-line-strong bg-white px-3 py-2 text-sm" /><span className="mt-1 block text-xs font-normal leading-5 text-ink-soft">Estado: informado para o cenário da sessão. Fonte: formulário BESS.</span></label>;
}

function ModeButton({ active, onClick, title, text }: { active: boolean; onClick: () => void; title: string; text: string }) {
  return <button type="button" onClick={onClick} aria-pressed={active} className={cn("min-h-28 rounded-xl border p-4 text-left transition-[border-color,background-color] hover:border-accent active:translate-y-px", active ? "border-2 border-accent bg-accent-soft" : "border-line bg-white")}><strong className="block">{title}</strong><span className="mt-2 block text-sm leading-5 text-ink-soft">{text}</span></button>;
}
