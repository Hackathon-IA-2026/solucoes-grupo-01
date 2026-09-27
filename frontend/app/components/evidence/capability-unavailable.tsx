import { WarningIcon } from "@phosphor-icons/react";

export function CapabilityUnavailable({ title, children, headingLevel = 3 }: { title: string; children: React.ReactNode; headingLevel?: 3 | 4 }) {
  const Heading = headingLevel === 4 ? "h4" : "h3";
  return <aside className="rounded-lg border border-warning/40 bg-amber-50 p-4 text-amber-950" role="status"><Heading className="flex items-center gap-2 font-semibold"><WarningIcon aria-hidden="true" />{title}</Heading><div className="mt-2 text-sm leading-6">{children}</div></aside>;
}
