export const numberFormatter = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
export const currencyFormatter = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
export const percentFormatter = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });
export const dateFormatter = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

export function formatEvidence(value: number | null, unit: string) {
  if (value === null) return "Indisponível";
  if (unit === "R$") return currencyFormatter.format(value);
  if (unit === "%") return percentFormatter.format(value / 100);
  return `${numberFormatter.format(value)} ${unit}`.trim();
}
