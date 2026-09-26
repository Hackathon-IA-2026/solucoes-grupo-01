import { index, route, type RouteConfig } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("exposicao", "routes/exposure.tsx"),
  route("manutencao", "routes/maintenance.tsx"),
  route("bateria", "routes/battery.tsx"),
  route("relatorio", "routes/report.tsx"),
  route("configuracoes", "routes/settings.tsx"),
  route("*", "routes/not-found.tsx"),
] satisfies RouteConfig;
