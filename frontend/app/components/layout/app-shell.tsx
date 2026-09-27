import { BatteryChargingIcon, ChartLineIcon, FileTextIcon, GearIcon, LightningIcon, WrenchIcon } from "@phosphor-icons/react";
import { Link, NavLink, useLocation } from "react-router";
import type { ReactNode } from "react";
import { AssetPicker } from "~/components/layout/asset-picker";
import { cn } from "~/lib/cn";

const primary = [
  { to: "/exposicao", label: "Exposição", Icon: ChartLineIcon },
  { to: "/manutencao", label: "Manutenção", Icon: WrenchIcon },
  { to: "/bateria", label: "Bateria", Icon: BatteryChargingIcon },
];

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <div className="min-h-[100dvh] overflow-x-clip">
      <a href="#main-content" className="fixed left-3 top-3 z-50 -translate-y-20 rounded-md bg-ink px-4 py-2 text-white focus:translate-y-0">Pular para o conteúdo</a>
      <header data-app-header className="no-print sticky top-0 z-50 border-b border-line bg-surface py-3">
        <div className="mx-2 flex w-auto flex-wrap items-center gap-x-4 gap-y-3 sm:mx-3">
          <Link to="/exposicao" className="flex min-h-11 shrink-0 items-center gap-3" translate="no">
            <span className="grid size-9 place-items-center rounded-lg bg-accent text-white"><LightningIcon weight="fill" aria-hidden="true" /></span>
            <strong className="tracking-tight">CurtaiLess</strong>
          </Link>
          <AssetPicker />
          <nav aria-label="Etapas da decisão" className="order-3 w-full min-w-0 sm:order-2 sm:ml-auto sm:w-auto">
            <ol className="flex gap-1 overflow-x-auto">
              {primary.map(({ to, label, Icon }) => (
                <li key={to} className="min-w-fit flex-1 sm:flex-none">
                  <NavLink to={to} className={({ isActive }) => cn("flex min-h-11 items-center justify-center gap-2 rounded-lg border border-transparent px-3 text-sm text-ink-soft hover:bg-accent-soft hover:text-ink sm:justify-start", isActive && "border-accent bg-accent-soft font-semibold text-ink")}>
                    <Icon aria-hidden="true" />{label}
                  </NavLink>
                </li>
              ))}
            </ol>
          </nav>
          <nav aria-label="Ações secundárias" className="order-2 ml-auto flex shrink-0 items-center gap-1 sm:order-3 sm:ml-0 sm:border-l sm:border-line sm:pl-1">
            <Link aria-label="Relatório" className={cn("inline-flex size-11 shrink-0 items-center justify-center gap-2 rounded-lg text-sm hover:bg-accent-soft sm:h-11 sm:w-auto sm:px-3", location.pathname === "/relatorio" && "bg-accent-soft font-semibold")} to="/relatorio"><FileTextIcon aria-hidden="true" /> <span className="hidden sm:inline">Relatório</span></Link>
            <Link aria-label="Fontes" className={cn("inline-flex size-11 shrink-0 items-center justify-center gap-2 rounded-lg text-sm hover:bg-accent-soft sm:h-11 sm:w-auto sm:px-3", location.pathname === "/configuracoes" && "bg-accent-soft font-semibold")} to="/configuracoes"><GearIcon aria-hidden="true" /> <span className="hidden sm:inline">Fontes</span></Link>
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className={cn("min-w-0", ["/exposicao", "/manutencao", "/bateria"].includes(location.pathname) ? "w-full max-w-none p-0" : "mx-auto max-w-[1600px] p-4 sm:p-6")}>{children}</main>
    </div>
  );
}
