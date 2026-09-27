import type { ReactNode } from "react";

export type HighlightItem = {
  label: string;
  value: ReactNode;
  unit?: string;
  detail?: string;
  emphasis?: "hero" | "primary" | "supporting";
};

type HighlightListProps = {
  items: HighlightItem[];
  label?: string;
  variant?: "default" | "metrics";
};

export function HighlightList({ items, label, variant = "default" }: HighlightListProps) {
  return (
    <dl data-highlight-list data-variant={variant} aria-label={label} className="divide-y divide-line">
      {items.map((item) => variant === "metrics" ? <MetricRow item={item} key={item.label} /> : <DefaultRow item={item} key={item.label} />)}
    </dl>
  );
}

function DefaultRow({ item }: { item: HighlightItem }) {
  return (
    <div data-highlight-row className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-6">
      <div className="min-w-0">
        <dt className="text-sm font-medium leading-6 text-ink">{item.label}</dt>
        {item.detail ? <p className="mt-1 text-sm leading-6 text-ink-soft">{item.detail}</p> : null}
      </div>
      <MetricValue item={item} className="text-2xl sm:text-right" />
    </div>
  );
}

function MetricRow({ item }: { item: HighlightItem }) {
  const emphasis = item.emphasis ?? "supporting";
  const valueClass = emphasis === "hero" ? "text-5xl leading-none" : "text-4xl leading-none";

  return (
    <div
      data-highlight-row
      data-emphasis={emphasis}
      data-layout="stacked"
      className="flex flex-col gap-3 py-5 first:pt-0 last:pb-0"
    >
      <div className="order-2 min-w-0">
        <dt className="text-base font-semibold leading-6 text-ink">{item.label}</dt>
        {item.detail ? <p className="mt-1 text-base leading-6 text-ink-soft">{item.detail}</p> : null}
      </div>
      <MetricValue item={item} className={`order-1 ${valueClass}`} />
    </div>
  );
}

function MetricValue({ item, className }: { item: HighlightItem; className: string }) {
  return (
    <dd className={`num whitespace-nowrap font-semibold tracking-tight text-ink ${className}`}>
      {item.value}
      {item.unit ? <> <span className="ml-1 font-sans text-[0.45em] font-semibold tracking-normal text-ink-soft">{item.unit}</span></> : null}
    </dd>
  );
}

export type CompositionItem = {
  label: string;
  value: number | null;
  displayValue: ReactNode;
};

export function MetricComposition({ items, label }: { items: CompositionItem[]; label: string }) {
  const weights = items.map((item) => Math.max(item.value ?? 0, 0));
  const hasWeight = weights.some((weight) => weight > 0);

  return (
    <section data-metric-composition aria-label={label}>
      <dl className="grid grid-cols-2 gap-5">
        {items.map((item) => (
          <div key={item.label} className="min-w-0">
            <dd className="num text-4xl font-semibold leading-none tracking-tight text-ink">{item.displayValue}</dd>
            <dt className="mt-3 text-base font-medium leading-6 text-ink-soft">{item.label}</dt>
          </div>
        ))}
      </dl>
      <div aria-hidden="true" className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-line">
        {items.map((item, index) => (
          <span
            data-composition-segment
            key={item.label}
            className={index === 0 ? "bg-accent" : "bg-line-strong"}
            style={{ flexBasis: 0, flexGrow: hasWeight ? weights[index] : 1 }}
          />
        ))}
      </div>
    </section>
  );
}
