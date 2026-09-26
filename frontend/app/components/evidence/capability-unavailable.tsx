import { WarningIcon } from "@phosphor-icons/react";

export function CapabilityUnavailable({ title, children }: { title: string; children: React.ReactNode }) {
  return <aside className="rounded-lg border border-warning/40 bg-amber-50 p-4 text-amber-950" role="status"><h3 className="flex items-center gap-2 font-semibold"><WarningIcon aria-hidden="true" />{title}</h3><div className="mt-2 text-sm leading-6">{children}</div></aside>;
}
