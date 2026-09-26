import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "~/lib/cn";

export function Panel({ title, description, action, children, className, ...props }: HTMLAttributes<HTMLElement> & { title?: string; description?: string; action?: ReactNode }) {
  return (
    <section className={cn("rounded-xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(16,42,42,.06)] sm:p-5", className)} {...props}>
      {title || description || action ? (
        <header className="mb-4 flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? <h2 className="text-lg font-semibold text-pretty">{title}</h2> : null}
            {description ? <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-soft">{description}</p> : null}
          </div>
          {action}
        </header>
      ) : null}
      {children}
    </section>
  );
}
