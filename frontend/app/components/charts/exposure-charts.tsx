import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartDataset, ChartPoint } from "~/domain/types";
import { ChartBody, ChartFrame, ChartSlot, DataTable } from "./chart-frame";

const colors = {
  energetic: "#102a2a",
  reliability: "#08756f",
  external: "#7b918d",
  unknown: "#c6b27d",
  primary: "#08756f",
  secondary: "#7b918d",
};

const historyTitle = "Exposição histórica por razão";
const historyDescription = "Participação mensal da energia não realizada, separada por razão registrada.";

function historyTable(data: ChartDataset, showState = true, fitContainer = false) {
  const headers = ["Mês", "Condição energética", "Confiabilidade da rede", "Indisponibilidade externa", "Motivo não informado"];
  const rows = data.points.map((point) => [String(point.label), value(point.energetic), value(point.reliability), value(point.external), value(point.unknown)]);
  return <DataTable caption="Valores mensais do curtailment por condição registrada" headers={showState ? [...headers, "Estado"] : headers} rows={showState ? rows.map((row) => [...row, data.evidence.state]) : rows} fitContainer={fitContainer} />;
}

function historyGraph(data: ChartDataset) {
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={data.points}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" fontSize={12} /><YAxis unit="%" fontSize={12} /><Tooltip /><Legend formatter={(label) => <span className="text-ink">{label}</span>} /><Bar dataKey="energetic" name="Razão energética" stackId="a" fill={colors.energetic} /><Bar dataKey="reliability" name="Confiabilidade" stackId="a" fill={colors.reliability} /><Bar dataKey="external" name="Indisponibilidade externa" stackId="a" fill={colors.external} /><Bar dataKey="unknown" name="Não caracterizada" stackId="a" fill={colors.unknown} /></BarChart></ResponsiveContainer>;
}

export function ExposureHistoryChart({ data }: { data: ChartDataset }) {
  return <ChartFrame title={historyTitle} description={historyDescription} evidence={data.evidence} table={historyTable(data)}>
    {historyGraph(data)}
  </ChartFrame>;
}

/** Same chart, rendered as one slot inside a shared card. */
export function ExposureHistorySlot({ data, showHeader = true }: { data: ChartDataset; showHeader?: boolean }) {
  return <ChartSlot title={historyTitle} description={historyDescription} evidence={data.evidence} showHeader={showHeader}>
    <ChartBody evidence={data.evidence} table={historyTable(data, showHeader, true)} showProvenance={showHeader} switchView>{historyGraph(data)}</ChartBody>
  </ChartSlot>;
}

function simpleTable(title: string, data: ChartDataset, showState = true, fitContainer = false) {
  const rows = data.points.map((point) => [String(point.label), point.value]);
  return <DataTable caption={`Valores de ${title}`} headers={showState ? ["Período ou categoria", data.evidence.unit, "Estado"] : ["Período ou categoria", data.evidence.unit]} rows={showState ? rows.map((row) => [...row, data.evidence.state]) : rows} fitContainer={fitContainer} />;
}

type SimpleChartVariant = "columns" | "horizontal" | "line";

function numericPointValue(point: ChartPoint) {
  return typeof point.value === "number" ? point.value : null;
}

function emphasizedIndexes(data: ChartDataset, count: number) {
  return new Set(data.points
    .map((point, index) => ({ index, value: numericPointValue(point) ?? Number.NEGATIVE_INFINITY }))
    .sort((a, b) => b.value - a.value)
    .slice(0, count)
    .map((point) => point.index));
}

function chartValue(valueToFormat: number | null, unit: string) {
  if (valueToFormat === null) return "Indisponível";
  return unit.includes("%") ? `${valueToFormat}%` : String(valueToFormat);
}

function columnGraph(data: ChartDataset, emphasizeCount: number, sparseTicks = false, maxBarSize = 30) {
  const emphasis = emphasizedIndexes(data, emphasizeCount);
  const points = data.points.map((point, index) => ({
    ...point,
    displayValue: emphasis.has(index) ? chartValue(numericPointValue(point), data.evidence.unit) : "",
  }));
  const percentage = data.evidence.unit.includes("%");

  return (
    <div data-chart-kind="columns" className="h-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points} barCategoryGap={sparseTicks ? "2%" : "12%"} margin={{ top: 22, right: 4, bottom: 0, left: -22 }}>
          <CartesianGrid stroke="#d7ddd8" vertical={false} />
          <XAxis dataKey="label" axisLine={false} tickLine={false} fontSize={11} interval={sparseTicks ? 1 : 0} />
          <YAxis axisLine={false} tickLine={false} fontSize={11} tickCount={3} width={38} domain={percentage ? [0, 100] : [0, "auto"]} />
          <Tooltip cursor={{ fill: "#d8eeea", opacity: 0.45 }} />
          <Bar dataKey="value" name={data.evidence.unit} fill={colors.secondary} radius={[6, 6, 0, 0]} maxBarSize={maxBarSize}>
            <LabelList dataKey="displayValue" position="top" fill="#355252" fontSize={11} fontWeight={600} />
            {points.map((point, index) => <Cell key={`${point.label}-${index}`} fill={emphasis.has(index) ? colors.primary : colors.secondary} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function horizontalGraph(data: ChartDataset, emphasizeCount: number) {
  const emphasis = emphasizedIndexes(data, emphasizeCount);
  const values = data.points.map(numericPointValue).filter((point): point is number => point !== null);
  const ceiling = data.evidence.unit.includes("%") ? 100 : Math.max(...values, 1);

  return (
    <ul data-chart-kind="horizontal" className="space-y-4 py-1">
      {data.points.map((point, index) => {
        const pointValue = numericPointValue(point);
        const width = pointValue === null ? 0 : Math.min(100, Math.max(0, pointValue / ceiling * 100));
        return (
          <li key={`${point.label}-${index}`}>
            <div className="mb-1.5 flex items-start justify-between gap-3 text-sm leading-5">
              <span className="min-w-0 font-medium text-ink">{point.label}</span>
              <span className="num shrink-0 font-semibold text-ink">{chartValue(pointValue, data.evidence.unit)}</span>
            </div>
            <div aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-line">
              <div className={`h-full rounded-full ${emphasis.has(index) ? "bg-accent" : "bg-line-strong"}`} style={{ width: `${width}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function lineGraph(data: ChartDataset, emphasizeCount: number) {
  const emphasis = emphasizedIndexes(data, emphasizeCount);
  const points = data.points.map((point, index) => ({
    ...point,
    displayValue: emphasis.has(index) ? chartValue(numericPointValue(point), data.evidence.unit) : "",
  }));
  const percentage = data.evidence.unit.includes("%");

  return (
    <div data-chart-kind="area" className="h-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 24, right: 12, bottom: 0, left: -22 }}>
          <CartesianGrid stroke="#d7ddd8" vertical={false} />
          <XAxis dataKey="label" axisLine={false} tickLine={false} fontSize={11} />
          <YAxis axisLine={false} tickLine={false} fontSize={11} tickCount={3} width={38} domain={percentage ? [0, 100] : [0, "auto"]} />
          <Tooltip />
          <Area type="monotone" dataKey="value" name={data.evidence.unit} stroke={colors.primary} strokeWidth={3} fill="#d8eeea" fillOpacity={0.8} dot={{ r: 3, fill: colors.primary, strokeWidth: 0 }} activeDot={{ r: 5 }}>
            <LabelList dataKey="displayValue" position="top" fill="#355252" fontSize={11} fontWeight={600} />
          </Area>
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function simpleGraph(data: ChartDataset, variant: SimpleChartVariant, emphasizeCount: number) {
  if (variant === "horizontal") return horizontalGraph(data, emphasizeCount);
  if (variant === "line") return lineGraph(data, emphasizeCount);
  return columnGraph(data, emphasizeCount);
}

export function SimpleHistoricalBar({ title, description, data }: { title: string; description: string; data: ChartDataset }) {
  return <ChartFrame title={title} description={description} evidence={data.evidence} table={simpleTable(title, data)}>
    {columnGraph(data, 1)}
  </ChartFrame>;
}

/** Same chart, rendered as one slot inside a shared card. */
export function SimpleHistoricalBarSlot({ title, description, data, showHeader = true, compactHeader = false, variant = "columns", emphasizeCount = 1, showTable = true, chartClassName, slotClassName }: { title: string; description: string; data: ChartDataset; showHeader?: boolean; compactHeader?: boolean; variant?: SimpleChartVariant; emphasizeCount?: number; showTable?: boolean; chartClassName?: string; slotClassName?: string }) {
  const resolvedChartClassName = chartClassName ?? (variant === "horizontal" ? "h-auto" : "h-52");
  return <ChartSlot title={title} description={description} evidence={data.evidence} showHeader={showHeader} compactHeader={compactHeader} className={slotClassName}>
    <ChartBody evidence={data.evidence} table={showTable ? simpleTable(title, data, showHeader && !compactHeader, true) : undefined} showProvenance={showHeader && !compactHeader} switchView={showTable} chartClassName={resolvedChartClassName}>{simpleGraph(data, variant, emphasizeCount)}</ChartBody>
  </ChartSlot>;
}

export function Forecast60dSlot({ data }: { data: ChartDataset }) {
  const title = "Previsão demonstrativa de curtailment para 60 dias";
  return <div data-exposure-forecast="60d">
    <ChartSlot title={title} description="Chance simulada de curtailment por semana do horizonte." evidence={data.evidence} showHeader={false}>
      <ChartBody evidence={data.evidence} table={simpleTable(title, data, false, true)} showProvenance={false} switchView chartClassName="h-72">{columnGraph(data, 3, true, 44)}</ChartBody>
    </ChartSlot>
  </div>;
}

function value(input: string | number | null | undefined) {
  return typeof input === "number" ? input : input ?? null;
}
