import { useEffect, useMemo, useState } from "react";
import { CalendarBlankIcon, ClockIcon, CurrencyDollarIcon, XIcon } from "@phosphor-icons/react";
import { Button } from "~/components/ui/button";
import { numberFormatter } from "~/lib/format";
import {
  SCENARIO_REFERENCE_DATE,
  type MaintenanceSuggestion,
  type PlantMaintenanceBooking,
} from "./maintenance-demo";

type MaintenanceSchedulingModalProps = {
  open: boolean;
  assetName: string;
  suggestion: MaintenanceSuggestion | null;
  scenarioPricePerMwh: number;
  onClose: () => void;
  onConfirm: (booking: PlantMaintenanceBooking) => void;
};

export function MaintenanceSchedulingModal({
  open,
  assetName,
  suggestion,
  scenarioPricePerMwh,
  onClose,
  onConfirm,
}: MaintenanceSchedulingModalProps) {
  const [start, setStart] = useState(() => suggestion?.start.slice(0, 16) ?? "");
  const [observations, setObservations] = useState("");
  const [error, setError] = useState("");
  const durationHours = suggestion?.durationHours ?? 24;

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const noticeDays = useMemo(() => {
    if (!start) return null;
    const difference = Date.parse(`${start}:00Z`) - Date.parse(SCENARIO_REFERENCE_DATE);
    if (!Number.isFinite(difference)) return null;
    return Math.max(0, Math.ceil(difference / 86_400_000));
  }, [start]);

  if (!open) return null;

  const confirm = () => {
    if (!start) {
      setError("Selecione a data e a hora inicial.");
      return;
    }
    if (!observations.trim()) {
      setError("Escreva as observações da intervenção.");
      return;
    }
    onConfirm({
      start: `${start}:00Z`,
      durationHours,
      observations: observations.trim(),
      suggestionId: suggestion?.id ?? null,
    });
  };

  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-ink/55 p-4" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="maintenance-modal-title"
        className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-xl border border-line bg-surface p-6 shadow-[0_24px_70px_rgba(16,42,42,.24)]"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line pb-4">
          <div>
            <h2 id="maintenance-modal-title" className="text-xl font-semibold text-ink">Agendar manutenção</h2>
            <p className="mt-1 text-sm leading-6 text-ink-soft">{assetName}. {suggestion ? `Janela sugerida número ${suggestion.rank}.` : "Data personalizada de 24 horas."}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar modal" className="grid size-11 shrink-0 place-items-center rounded-lg text-ink-soft hover:bg-accent-soft hover:text-ink">
            <XIcon size={20} aria-hidden="true" />
          </button>
        </header>

        <form className="mt-5 space-y-5" onSubmit={(event) => { event.preventDefault(); confirm(); }}>
          <label className="block text-sm font-semibold text-ink" htmlFor="maintenance-start">
            Data e hora inicial
            <input
              id="maintenance-start"
              type="datetime-local"
              required
              min="2026-10-01T00:00"
              max="2026-10-31T23:59"
              value={start}
              onChange={(event) => { setStart(event.target.value); setError(""); }}
              className="mt-2 min-h-11 w-full rounded-lg border-2 border-line-strong bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none"
            />
          </label>

          <dl className="grid gap-3 sm:grid-cols-3">
            <ReadOnlyMetric icon={<ClockIcon size={18} aria-hidden="true" />} label="Duração" value={`${durationHours} horas`} />
            <ReadOnlyMetric icon={<CalendarBlankIcon size={18} aria-hidden="true" />} label="Antecedência no cenário" value={noticeDays === null ? "Aguardando data" : `${noticeDays} dias`} />
            <ReadOnlyMetric icon={<CurrencyDollarIcon size={18} aria-hidden="true" />} label="Preço de cenário" value={`R$ ${numberFormatter.format(scenarioPricePerMwh)}/MWh`} />
          </dl>

          <label className="block text-sm font-semibold text-ink" htmlFor="maintenance-observations">
            Observações
            <textarea
              id="maintenance-observations"
              rows={4}
              value={observations}
              onChange={(event) => { setObservations(event.target.value); setError(""); }}
              placeholder="Descreva restrições operacionais e orientações para a equipe."
              className="mt-2 w-full rounded-lg border-2 border-line-strong bg-white px-3 py-2 text-sm leading-6 focus:border-accent focus:outline-none"
            />
          </label>

          {error ? <p role="alert" className="text-sm font-semibold text-danger">{error}</p> : null}

          <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
            <Button type="button" onClick={onClose}>Cancelar</Button>
            <Button type="submit" variant="primary">Confirmar agendamento</Button>
          </div>
        </form>
      </section>
    </div>
  );
}

function ReadOnlyMetric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-canvas p-3">
      <div className="flex items-center gap-2 text-ink-soft">{icon}<dt className="text-xs">{label}</dt></div>
      <dd className="num mt-2 text-sm font-semibold text-ink">{value}</dd>
    </div>
  );
}
