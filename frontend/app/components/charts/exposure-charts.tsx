import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartDataset } from "~/domain/types";
import { ChartFrame, DataTable } from "./chart-frame";

const colors = { energetic: "#102a2a", reliability: "#08756f", external: "#7b918d", unknown: "#c6b27d" };

export function ExposureHistoryChart({ data }: { data: ChartDataset }) {
  return <ChartFrame title="Exposição histórica por razão" description="Participação mensal da energia não realizada, separada por razão registrada." evidence={data.evidence} table={<DataTable caption="Valores mensais da exposição histórica por razão" headers={["Mês", "Energética", "Confiabilidade", "Externa", "Não caracterizada", "Estado"]} rows={data.points.map((point) => [String(point.label), value(point.energetic), value(point.reliability), value(point.external), value(point.unknown), data.evidence.state])} />}>
    <ResponsiveContainer width="100%" height="100%"><BarChart data={data.points}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" fontSize={12} /><YAxis unit="%" fontSize={12} /><Tooltip /><Legend formatter={(label) => <span className="text-ink">{label}</span>} /><Bar dataKey="energetic" name="Razão energética" stackId="a" fill={colors.energetic} /><Bar dataKey="reliability" name="Confiabilidade" stackId="a" fill={colors.reliability} /><Bar dataKey="external" name="Indisponibilidade externa" stackId="a" fill={colors.external} /><Bar dataKey="unknown" name="Não caracterizada" stackId="a" fill={colors.unknown} /></BarChart></ResponsiveContainer>
  </ChartFrame>;
}

export function SimpleHistoricalBar({ title, description, data }: { title: string; description: string; data: ChartDataset }) {
  return <ChartFrame title={title} description={description} evidence={data.evidence} table={<DataTable caption={`Valores de ${title}`} headers={["Período ou categoria", data.evidence.unit, "Estado"]} rows={data.points.map((point) => [String(point.label), point.value, data.evidence.state])} />}>
    <ResponsiveContainer width="100%" height="100%"><BarChart data={data.points}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Bar dataKey="value" name={data.evidence.unit} fill="#08756f" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer>
  </ChartFrame>;
}

function value(input: string | number | null | undefined) {
  return typeof input === "number" ? input : input ?? null;
}
