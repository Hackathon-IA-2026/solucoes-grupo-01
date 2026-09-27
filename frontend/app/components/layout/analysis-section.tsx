import type { ReactNode } from "react";

export type AnalysisSectionProps = {
  id: string;
  title: string;
  illustration: ReactNode;
  analysis: ReactNode;
  children: ReactNode;
};

/**
 * One viewport-sized unit of the exposure page: an asset illustration on the
 * left, the AI reading in the middle and one data card on the right. All three
 * columns have the same width.
 */
export function AnalysisSection({ id, title, illustration, analysis, children }: AnalysisSectionProps) {
  return (
    <section id={id} data-analysis-section={id} aria-labelledby={`${id}-title`} className="min-h-[calc(100dvh-8rem)] scroll-mt-28 px-4 py-8 sm:px-6 xl:px-8 xl:py-10">
      <div data-analysis-grid className="relative isolate grid items-start gap-6 xl:grid-cols-3">
        <div data-reserved-column className="relative z-0 hidden min-w-0 xl:block">{illustration}</div>
        <div data-ai-analysis className="relative z-10 min-w-0 rounded-xl border border-accent/30 bg-accent-soft p-6">
          <h2 id={`${id}-title`} className="text-2xl font-semibold leading-8 text-pretty">{title}</h2>
          <div className="mt-5 space-y-4 text-base leading-7 text-ink">{analysis}</div>
        </div>
        <div data-section-data-column className="relative z-10 min-w-0">{children}</div>
      </div>
    </section>
  );
}
