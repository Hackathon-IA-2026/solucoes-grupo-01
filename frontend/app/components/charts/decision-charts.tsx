import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BatteryScenario, EvidenceMetadata, EvidenceValue, MaintenanceWindow } from "~/domain/types";
import { ChartFrame, DataTable } from "./chart-frame";

export function MaintenanceComparisonChart({ windows }: { windows: MaintenanceWindow[] }) {
  const data = windows.filter((window) => window.eligible).map((window) => ({ label: window.baseline ? "Janela-base" : `Alternativa ${window.rank}`, loss: window.interventionLoss.value, difference: window.differenceFromBaseline.value }));
  const baselineValue = windows.find((window) => window.baseline)?.interventionLoss.value ?? undefined;
  const evidence = withoutValue(windows[0].interventionLoss);
  return <ChartFrame title="Comparação com a janela-base" description="Perda de oportunidade durante a intervenção. Valores abaixo da base indicam menor perda no cenário." evidence={evidence} table={<DataTable caption="Comparação das janelas elegíveis com a janela-base" headers={["Janela", "Perda (MWh)", "Diferença (MWh)", "Estado"]} rows={data.map((point) => [point.label, point.loss, point.difference, evidence.state])} />}>
    <ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" fontSize={12} /><YAxis unit=" MWh" fontSize={12} /><Tooltip />{typeof baselineValue === "number" ? <ReferenceLine y={baselineValue} stroke="#9a5d00" strokeDasharray="4 4" label="Base" /> : null}<Bar dataKey="loss" name="Perda da intervenção" fill="#08756f" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer>
  </ChartFrame>;
}

export function BatterySensitivityChart({ scenario }: { scenario: BatteryScenario }) {
  const data = scenario.sensitivity;
  return <ChartFrame title="Sensibilidade ao preço parametrizado" description="Uma variável muda por vez; as demais premissas permanecem fixas." evidence={data.evidence} table={<DataTable caption="Sensibilidade econômica ao preço parametrizado" headers={["Preço", "Benefício (R$)", "Lacuna (R$)", "Estado"]} rows={data.points.map((point) => [String(point.label), point.benefit as number | null, point.gap as number | null, data.evidence.state])} />}>
    <ResponsiveContainer width="100%" height="100%"><LineChart data={data.points}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Legend /><Line type="monotone" dataKey="benefit" name="Benefício parametrizado" stroke="#08756f" strokeWidth={3} /><Line type="monotone" dataKey="gap" name="Lacuna econômica" stroke="#9d2d32" strokeWidth={3} /></LineChart></ResponsiveContainer>
  </ChartFrame>;
}

function withoutValue(evidence: EvidenceValue): EvidenceMetadata {
  return { unit: evidence.unit, period: evidence.period, source: evidence.source, dataVersion: evidence.dataVersion, method: evidence.method, state: evidence.state, unavailableReason: evidence.unavailableReason };
}
