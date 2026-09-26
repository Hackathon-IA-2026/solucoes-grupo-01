import { zodResolver } from "@hookform/resolvers/zod";
import { cloneElement, type ReactElement } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "~/components/ui/button";
import { Panel } from "~/components/ui/panel";
import type { InterventionRequest } from "~/domain/types";

const ptDate = z.string().regex(/^\d{2}\/\d{2}\/\d{4}$/, "Use DD/MM/AAAA").refine(isValidPtDate, "Informe uma data válida").transform(toIsoDate);
const ptDateTime = z.string().regex(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/, "Use DD/MM/AAAA HH:MM").refine((value) => isValidPtDate(value.slice(0, 10)), "Informe uma data válida").transform(toIsoDateTime);

const schema = z.object({
  duration: z.coerce.number().min(1, "Informe ao menos 1 hora").max(168, "Use no máximo 168 horas"),
  notice: z.coerce.number().min(1, "Informe a antecedência"),
  start: ptDate,
  end: ptDate,
  unavailable: z.string().min(1, "Informe os dias ou horários indisponíveis"),
  baseline: ptDateTime,
  acceptableOutage: z.string().min(1, "Descreva as indisponibilidades aceitáveis"),
  operationalNotes: z.string().min(1, "Descreva as restrições operacionais"),
  price: z.preprocess((value) => value === "" ? null : Number(value), z.number().positive("Use um preço positivo").nullable()),
}).superRefine((values, context) => {
  const start = new Date(`${values.start}T00:00:00`);
  const end = new Date(`${values.end}T00:00:00`);
  const endExclusive = new Date(end.getTime() + 24 * 3_600_000);
  const baseline = new Date(values.baseline);
  if (end < start) context.addIssue({ code: "custom", path: ["end"], message: "O fim deve ocorrer depois do início" });
  if (baseline < start || baseline >= endExclusive) context.addIssue({ code: "custom", path: ["baseline"], message: "A janela-base deve estar dentro do intervalo elegível" });
  if (values.duration > (endExclusive.getTime() - start.getTime()) / 3_600_000) context.addIssue({ code: "custom", path: ["duration"], message: "A duração não cabe no intervalo elegível" });
});
type InterventionInput = z.input<typeof schema>;
export type InterventionValues = z.output<typeof schema>;

export function InterventionForm({ initialValues, onRank }: { initialValues: InterventionRequest; onRank: (values: InterventionValues) => Promise<void> }) {
  const defaultValues: InterventionInput = { ...initialValues, start: formatPtDate(initialValues.start), end: formatPtDate(initialValues.end), baseline: formatPtDateTime(initialValues.baseline) };
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<InterventionInput, unknown, InterventionValues>({ resolver: zodResolver(schema), defaultValues });
  return <Panel title="Parâmetros da intervenção" description="Esta demonstração possui um perfil materializado por ativo. Alterações sem resposta correspondente da API não exibem resultados antigos.">
    <form onSubmit={handleSubmit(onRank)} className="grid gap-4 sm:grid-cols-2" noValidate>
      <Field label="Duração (horas)" error={errors.duration?.message}><input type="number" inputMode="numeric" {...register("duration")} /></Field>
      <Field label="Antecedência mínima (dias)" error={errors.notice?.message}><input type="number" inputMode="numeric" {...register("notice")} /></Field>
      <Field label="Início do intervalo elegível" error={errors.start?.message} hint="Formato: DD/MM/AAAA"><input type="text" inputMode="numeric" placeholder="DD/MM/AAAA" {...register("start")} /></Field>
      <Field label="Fim do intervalo elegível" error={errors.end?.message} hint="Formato: DD/MM/AAAA"><input type="text" inputMode="numeric" placeholder="DD/MM/AAAA" {...register("end")} /></Field>
      <Field label="Dias e horários indisponíveis" error={errors.unavailable?.message}><input type="text" {...register("unavailable")} /></Field>
      <Field label="Janela-base" error={errors.baseline?.message} hint="Formato: DD/MM/AAAA HH:MM"><input type="text" inputMode="numeric" placeholder="DD/MM/AAAA HH:MM" {...register("baseline")} /></Field>
      <Field label="Indisponibilidades aceitáveis" error={errors.acceptableOutage?.message}><input type="text" {...register("acceptableOutage")} /></Field>
      <Field label="Preço de cenário (R$/MWh)" error={errors.price?.message} hint="Se ficar vazio, o ranking energético continua e o custo fica indisponível."><input type="number" inputMode="decimal" {...register("price")} /></Field>
      <div className="sm:col-span-2"><Field label="Observações e restrições operacionais" error={errors.operationalNotes?.message}><textarea rows={3} {...register("operationalNotes")} /></Field></div>
      <div className="sm:col-span-2"><Button type="submit" variant="primary" disabled={isSubmitting}>{isSubmitting ? "Consultando resposta materializada…" : "Comparar janelas"}</Button></div>
    </form>
  </Panel>;
}

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactElement<Record<string, unknown>> }) {
  const id = `field-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const input = cloneElement(children, { id, className: "mt-2 min-h-11 w-full rounded-lg border-2 border-line-strong bg-white px-3 py-2 text-sm shadow-[inset_0_1px_1px_rgba(16,42,42,.05)]", "aria-invalid": Boolean(error), "aria-describedby": error ? `${id}-error` : hint ? `${id}-hint` : undefined, autoComplete: "off" });
  return <label htmlFor={id} className="text-sm font-semibold">{label}{input}{hint ? <span id={`${id}-hint`} className="mt-1 block text-xs font-normal leading-5 text-ink-soft">{hint}</span> : null}{error ? <span id={`${id}-error`} role="alert" className="mt-1 block text-xs font-normal text-danger">{error}</span> : null}</label>;
}

function isValidPtDate(value: string) {
  const [day, month, year] = value.split("/").map(Number);
  if (!day || !month || !year) return false;
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}
function toIsoDate(value: string) { const [day, month, year] = value.split("/"); return `${year}-${month}-${day}`; }
function toIsoDateTime(value: string) { const [date, time] = value.split(" "); return `${toIsoDate(date)}T${time}`; }
function formatPtDate(value: string) { const [year, month, day] = value.slice(0, 10).split("-"); return `${day}/${month}/${year}`; }
function formatPtDateTime(value: string) { return `${formatPtDate(value)} ${value.slice(11, 16)}`; }
