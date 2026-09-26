import type { ReactNode } from "react";

export function DecisionWorkspace({ title, description, status, context, children }: { title: string; description: string; status: string; context: ReactNode; children: ReactNode }) {
  return (
    <div>
      <header className="mb-6 flex flex-col gap-3 border-b border-line pb-5 xl:flex-row xl:items-end xl:justify-between">
        <div><h1 tabIndex={-1} className="text-3xl font-semibold tracking-tight text-pretty">{title}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-ink-soft">{description}</p></div>
        <span className="w-fit rounded-md border border-warning/30 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">{status}</span>
      </header>
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(320px,2fr)_minmax(520px,3fr)]">
        <aside className="min-w-0 xl:sticky xl:top-5">{context}</aside>
        <div className="min-w-0 space-y-5">{children}</div>
      </div>
    </div>
  );
}
