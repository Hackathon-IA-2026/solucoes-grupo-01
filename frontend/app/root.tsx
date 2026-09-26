import type { ReactNode } from "react";
import { Links, Meta, Outlet, Scripts, ScrollRestoration } from "react-router";
import { AnalysisProvider } from "~/state/analysis-context";
import { AppShell } from "~/components/layout/app-shell";
import "./app.css";

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#f5f3ed" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return (
    <AnalysisProvider>
      <AppShell>
        <Outlet />
      </AppShell>
    </AnalysisProvider>
  );
}
