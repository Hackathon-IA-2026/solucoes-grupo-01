import { Link } from "react-router";

export default function NotFoundRoute() {
  return <div className="mx-auto max-w-xl py-20 text-center"><h1 className="text-3xl font-semibold">Página não encontrada</h1><p className="mt-3 text-ink-soft">A rota informada não faz parte do fluxo do CurtailLess.</p><Link className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-ink px-4 py-2 font-semibold text-white" to="/exposicao">Abrir Exposição</Link></div>;
}
