import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { numberFormatter } from "~/lib/format";
import type { MaintenanceReductionPoint } from "./maintenance-demo";

export function MaintenanceReductionChart({ points }: { points: MaintenanceReductionPoint[] }) {
  return (
    <div data-maintenance-reduction-chart className="h-80 min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 12, right: 10, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#d7ddd8" vertical={false} />
          <XAxis dataKey="label" axisLine={false} tickLine={false} interval={6} minTickGap={18} fontSize={10} />
          <YAxis axisLine={false} tickLine={false} width={54} unit=" MWh" fontSize={10} />
          <Tooltip content={<MaintenanceReductionTooltip />} />
          <Legend formatter={(label) => <span className="text-ink">{label}</span>} />
          <Line dataKey="curtailmentBeforeMwh" name="Curtailment previsto" stroke="#718185" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
          <Line dataKey="residualCurtailmentMwh" name="Após manutenções" stroke="#08756f" strokeWidth={3} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function MaintenanceReductionTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: MaintenanceReductionPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const totalReduction = point.scheduledReductionMwh + point.plantReductionMwh;
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs leading-5 shadow-sm">
      <p className="font-semibold text-ink">{formatDate(point.date)}</p>
      <p className="text-ink-soft">Curtailment previsto: <span className="num font-semibold text-ink">{numberFormatter.format(point.curtailmentBeforeMwh)} MWh</span></p>
      <p className="text-ink-soft">Geração reduzida: <span className="num font-semibold text-ink">{numberFormatter.format(totalReduction)} MWh</span></p>
      <p className="text-ink-soft">Chance de curtailment: <span className="num font-semibold text-ink">{numberFormatter.format(point.curtailmentProbability * 100)}%</span></p>
      <p className="text-ink-soft">Curtailment residual: <span className="num font-semibold text-ink">{numberFormatter.format(point.residualCurtailmentMwh)} MWh</span></p>
    </div>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}
