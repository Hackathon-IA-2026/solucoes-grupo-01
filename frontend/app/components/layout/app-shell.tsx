import { FileTextIcon, GearIcon, LightningIcon } from "@phosphor-icons/react";
import { Link, NavLink, useLocation } from "react-router";
import type { ReactNode } from "react";
import { assets } from "~/domain/fixtures";
import { useAnalysis } from "~/state/use-analysis";
import { cn } from "~/lib/cn";

const primary = [
  { to: "/exposicao", label: "Exposição", number: "01" },
  { to: "/manutencao", label: "Manutenção", number: "02" },
  { to: "/bateria", label: "Bateria", number: "03" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { state, selectAsset } = useAnalysis();
  const location = useLocation();
  const activeAsset = assets.find((asset) => asset.id === state.assetId) ?? assets[0];
  return (
    <div className="min-h-[100dvh] overflow-x-clip">
      <a href="#main-content" className="fixed left-3 top-3 z-50 -translate-y-20 rounded-md bg-ink px-4 py-2 text-white focus:translate-y-0">Pular para o conteúdo</a>
      <div className="bg-ink px-4 py-2 text-center text-sm leading-5 text-white sm:px-6">
        Demonstração: histórico real do ONS via backend e MCP demonstrativo; perspectiva histórica de 30 dias; ranking prototípico; reservas e telemetria simuladas; BESS como cenário; orientação Bedrock limitada a evidências fechadas, com contingência determinística.
      </div>
      <header className="border-b border-line bg-surface px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4">
          <Link to="/exposicao" className="flex min-h-11 items-center gap-3" translate="no">
            <span className="grid size-9 place-items-center rounded-lg bg-accent text-white"><LightningIcon weight="fill" aria-hidden="true" /></span>
            <span><strong className="block tracking-tight">CurtailLess</strong><span className="block text-xs text-ink-soft">Decisão por ativo</span></span>
          </Link>
          <label className="order-3 flex w-full min-w-0 flex-col gap-1 text-xs font-semibold text-ink-soft sm:order-none sm:ml-auto sm:w-auto sm:min-w-[260px] sm:flex-row sm:items-center sm:gap-2">
            Ativo
            <select className="min-h-11 w-full min-w-0 rounded-lg border border-line bg-white px-3 text-sm text-ink" value={state.assetId} onChange={(event) => selectAsset(event.target.value)} name="asset" autoComplete="off">
              {assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name} | {asset.technology}</option>)}
            </select>
          </label>
          <span className="rounded-md bg-accent-soft px-3 py-2 text-xs font-semibold">{activeAsset.technology}</span>
          <nav aria-label="Ações secundárias" className="flex items-center gap-1">
            <Link aria-label="Relatório" className={cn("inline-flex size-11 shrink-0 items-center justify-center gap-2 rounded-lg text-sm hover:bg-accent-soft sm:h-11 sm:w-auto sm:px-3", location.pathname === "/relatorio" && "bg-accent-soft font-semibold")} to="/relatorio"><FileTextIcon aria-hidden="true" /> <span className="hidden sm:inline">Relatório</span></Link>
            <Link aria-label="Fontes e qualidade" className={cn("inline-flex size-11 shrink-0 items-center justify-center gap-2 rounded-lg text-sm hover:bg-accent-soft sm:h-11 sm:w-auto sm:px-3", location.pathname === "/configuracoes" && "bg-accent-soft font-semibold")} to="/configuracoes"><GearIcon aria-hidden="true" /> <span className="hidden sm:inline">Fontes e qualidade</span></Link>
          </nav>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1600px] lg:grid-cols-[190px_minmax(0,1fr)]">
        <nav aria-label="Etapas da decisão" className="no-print border-b border-line bg-surface p-3 lg:sticky lg:top-0 lg:h-[calc(100dvh-114px)] lg:border-b-0 lg:border-r lg:p-4">
          <ol className="flex gap-2 overflow-x-auto lg:flex-col">
            {primary.map((item) => (
              <li key={item.to} className="min-w-fit lg:w-full">
                <NavLink to={item.to} className={({ isActive }) => cn("flex min-h-12 items-center gap-3 rounded-lg border border-transparent px-3 py-2 text-sm text-ink-soft hover:bg-accent-soft hover:text-ink", isActive && "border-accent bg-accent-soft font-semibold text-ink")}>
                  <span className="num text-xs" aria-hidden="true">{item.number}</span>{item.label}
                </NavLink>
              </li>
            ))}
          </ol>
          <div className="mt-8 hidden text-xs leading-5 text-ink-soft lg:block">
            <p className="font-semibold text-ink">Fluxo da decisão</p>
            <p className="mt-2">Entenda a exposição, escolha a manutenção e avalie a bateria sobre a perda residual.</p>
          </div>
        </nav>
        <main id="main-content" tabIndex={-1} className="min-w-0 p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
