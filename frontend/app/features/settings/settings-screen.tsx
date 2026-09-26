import { CheckCircleIcon, WarningIcon } from "@phosphor-icons/react";
import { Panel } from "~/components/ui/panel";
import { DataQualityPanel } from "~/components/evidence/data-quality";
import { EvidenceMetric } from "~/components/evidence/evidence";
import { dataQualityByAsset, modelResearch } from "~/domain/fixtures";
import { useAnalysis } from "~/state/use-analysis";

const sources = [
  ["S3 público do ONS", "Disponível", "Histórico, exposição, razões, pontos e validação"],
  ["MCP do ONS", "Conexão demonstrada", "Catálogo e descoberta; frontend não consulta diretamente"],
  ["Telemetria do cliente", "Ausente", "Série sintética na demonstração"],
  ["Previsão meteorológica", "Ausente", "A perspectiva permanece histórica"],
  ["PLD e dados comerciais", "Integração ausente", "Preço parametrizado"],
  ["Cadastro de manutenção", "Entrada do usuário", "Duração, restrições e janela-base"],
  ["Bedrock", "Orientação demonstrativa", "Bloco fechado de evidências e contingência determinística"],
  ["Corpus normativo", "Parcial", "Orientação somente com fonte versionada"],
];

export function SettingsScreen() {
  const { state } = useAnalysis();
  const dataQuality = dataQualityByAsset[state.assetId] ?? dataQualityByAsset["asset-wind"];
  return <div className="mx-auto max-w-6xl space-y-5"><header className="border-b border-line pb-5"><h1 className="text-3xl font-semibold">Fontes, qualidade e modelo</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-ink-soft">Área técnica secundária. O frontend recebe objetos calculados pela API e não lê diretamente o bucket público do ONS.</p></header>
    <Panel title="Estado das fontes"><div className="max-w-full overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><caption className="sr-only">Estado das fontes de dados e serviços</caption><thead><tr><th scope="col" className="border-b border-line p-3">Fonte</th><th scope="col" className="border-b border-line p-3">Estado</th><th scope="col" className="border-b border-line p-3">Uso</th></tr></thead><tbody>{sources.map(([source, state, use]) => <tr key={source}><td className="border-b border-line/70 p-3 font-semibold">{source}</td><td className="border-b border-line/70 p-3">{state}</td><td className="border-b border-line/70 p-3 text-ink-soft">{use}</td></tr>)}</tbody></table></div></Panel>
    <DataQualityPanel quality={dataQuality} />
    <Panel title="Estado da pesquisa do modelo de seis horas" description="As métricas abaixo demonstram sinal histórico. Não sustentam previsão de 30 dias, alerta validado ou generalização para solar.">
      <div className="grid gap-3 sm:grid-cols-2"><EvidenceMetric label="AUC no sistema" evidence={modelResearch.systemAuc} /><EvidenceMetric label="AUC por conjunto" evidence={modelResearch.setAuc} /></div>
      <p className="mt-4 rounded-lg bg-canvas p-3 text-sm text-ink-soft"><strong className="text-ink">Estado da execução:</strong> {modelResearch.executionState}</p>
      <h3 className="mt-5 font-semibold">Limitações metodológicas obrigatórias</h3><ul className="mt-3 space-y-2">{modelResearch.limitations.map((item) => <li className="flex items-start gap-2 text-sm text-ink-soft" key={item}><WarningIcon className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />{item}</li>)}</ul>
    </Panel>
    <Panel title="Fluxo de ingestão"><ol className="grid gap-2 text-sm sm:grid-cols-4"><li className="rounded-lg bg-accent-soft p-3"><CheckCircleIcon aria-hidden="true" /> S3 raw imutável</li><li className="rounded-lg bg-accent-soft p-3"><CheckCircleIcon aria-hidden="true" /> Validação e Parquet</li><li className="rounded-lg bg-accent-soft p-3"><CheckCircleIcon aria-hidden="true" /> DynamoDB e API</li><li className="rounded-lg bg-accent-soft p-3"><CheckCircleIcon aria-hidden="true" /> Frontend CurtailLess</li></ol></Panel>
  </div>;
}
