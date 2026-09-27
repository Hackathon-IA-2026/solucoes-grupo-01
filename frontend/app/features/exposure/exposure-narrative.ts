import type { Asset, AssetExposure, ChartDataset, ChartPoint, DataQuality, ForecastWindow } from "~/domain/types";
import { formatEvidence } from "~/lib/format";

export type ExposureNarrative = Record<string, string[]>;

const reasonLabels: Record<string, string> = {
  "Razão energética": "condições energéticas do sistema",
  Confiabilidade: "confiabilidade da rede",
  "Indisponibilidade externa": "indisponibilidade fora da usina",
  "Não caracterizada": "motivos não informados",
};

const originLabels: Record<string, string> = {
  Sistêmica: "condições do sistema",
  Local: "condições próximas à usina",
  "Não informada": "origem não informada",
};

const weekdayLabels: Record<string, string> = {
  "seg.": "segunda-feira",
  "ter.": "terça-feira",
  "qua.": "quarta-feira",
  "qui.": "quinta-feira",
  "sex.": "sexta-feira",
  "sáb.": "sábado",
  "dom.": "domingo",
};

function sentenceStart(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function rankedPoints(data: ChartDataset): ChartPoint[] {
  return [...data.points].sort((a, b) => Number(b.value) - Number(a.value));
}

function describePoint(point: ChartPoint | undefined, labels?: Record<string, string>) {
  if (!point) return { label: "sem informação suficiente", value: "indisponível" };
  const label = labels?.[point.label] ?? point.label.toLowerCase();
  const value = point.value === null || point.value === undefined ? "indisponível" : `${point.value}%`;
  return { label, value };
}

function describeOtherWindows(windows: ForecastWindow[]) {
  return windows.slice(1).map((window) => `${window.label}, com ${formatEvidence(window.likelihood.value, window.likelihood.unit)}`).join(", e em ");
}

export function buildExposureNarrative({ asset, exposure, quality, windows }: { asset: Asset; exposure: AssetExposure; quality: DataQuality; windows: ForecastWindow[] }): ExposureNarrative {
  const total = formatEvidence(exposure.summary.total.value, exposure.summary.total.unit);
  const characterized = formatEvidence(exposure.summary.characterized.value, exposure.summary.characterized.unit);
  const simultaneous = formatEvidence(exposure.summary.simultaneous.value, exposure.summary.simultaneous.unit);
  const exclusive = formatEvidence(exposure.summary.exclusive.value, exposure.summary.exclusive.unit);
  const reasons = rankedPoints(exposure.reasons);
  const origins = rankedPoints(exposure.origins);
  const weekdays = rankedPoints(exposure.seasonality);
  const hours = rankedPoints(exposure.hourly);
  const reason = describePoint(reasons[0], reasonLabels);
  const secondReason = describePoint(reasons[1], reasonLabels);
  const origin = describePoint(origins[0], originLabels);
  const weekday = describePoint(weekdays[0], weekdayLabels);
  const secondWeekday = describePoint(weekdays[1], weekdayLabels);
  const hour = describePoint(hours[0]);
  const secondHour = describePoint(hours[1]);
  const priorityWindow = windows[0] ?? null;
  const otherWindows = describeOtherWindows(windows);

  return {
    "secao-ativo": [
      `${asset.name} está em ${asset.location} e aparece ligado ao ${asset.connectionPoint}. O mesmo ponto reúne ${asset.anonymousEntities} outras usinas ou conjuntos, que formam o contexto usado para comparar o comportamento deste ativo com o entorno.`,
      `A análise observa quando as restrições aparecem somente nesta usina e quando alcançam outros ativos ligados ao ponto. Essa comparação ajuda a distinguir um padrão concentrado no ativo de um movimento mais amplo no ponto de conexão.`,
      `A próxima evolução é combinar esse contexto com geração, disponibilidade e intervenções da própria usina. Com esses dados, a previsão poderá separar períodos de maior curtailment de períodos em que a energia continuaria disponível para venda.`,
    ],
    "secao-resumo": [
      `No período analisado, ${total} de geração potencial deixaram de ser produzidos durante restrições. O ONS informou o motivo associado a ${characterized} desse volume, o que permite interpretar quase toda a exposição observada.`,
      `${simultaneous} dos registros também aparecem em outras usinas ou conjuntos ligados ao mesmo ponto. Os ${exclusive} restantes se concentram somente neste ativo, mostrando quanto do padrão observado foi compartilhado e quanto ficou restrito à usina.`,
      `A parcela compartilhada indica que a análise das próximas janelas deve considerar o comportamento do ponto de conexão, além do histórico individual. A parcela exclusiva ajuda a identificar períodos em que disponibilidade e operação próprias ganham mais peso.`,
      `Esse retrato define a base da previsão de 60 dias: volume exposto, cobertura dos motivos e alcance dos cortes. As próximas seções mostram quando a atenção aumenta e quais condições acompanharam os eventos anteriores.`,
    ],
    "secao-previsao": [
      priorityWindow
        ? `${priorityWindow.label} é a principal janela de atenção nos próximos 60 dias, com ${formatEvidence(priorityWindow.likelihood.value, priorityWindow.likelihood.unit)} de chance de curtailment. Esse é o período em que o cenário aponta a maior concentração de risco para a usina.`
        : `A previsão de 60 dias ainda não possui janelas suficientes para destacar um período prioritário.`,
      otherWindows
        ? `Outras elevações aparecem em ${otherWindows}. A sequência mostra se o risco fica concentrado em uma única semana ou retorna em diferentes momentos do horizonte.`
        : `Não há uma segunda janela de atenção registrada neste horizonte.`,
      `O percentual representa a chance de ocorrer curtailment em cada semana, e não a parcela de energia que será cortada. Semanas mais altas pedem mais atenção; semanas mais baixas oferecem melhores candidatas para comparar uma intervenção.`,
      `Para escolher uma janela de manutenção, a usina pode cruzar essa curva com duração do serviço, disponibilidade do ativo e energia ainda vendável. O ranking de manutenção fará essa comparação usando as condições informadas pela equipe.`,
    ],
    "secao-razao-origem": [
      `${sentenceStart(reason.label)} concentra a maior parcela do histórico, com ${reason.value}. Em seguida aparecem ${secondReason.label}, com ${secondReason.value}, mostrando quais condições acompanharam a maior parte da energia restringida.`,
      `Na leitura de abrangência, ${origin.label} representam ${origin.value} do volume analisado. Esse resultado mostra se os registros se concentram no sistema ou em condições mais próximas da usina.`,
      `As duas distribuições respondem a perguntas diferentes: uma informa a condição registrada para o corte; a outra mostra a abrangência atribuída ao evento. Lidas em conjunto, elas ajudam a reconhecer quais contextos merecem maior atenção na previsão.`,
      `Se as próximas semanas de maior chance coincidirem com o padrão dominante do histórico, a usina ganha um sinal adicional para priorizar essas janelas na análise de manutenção e operação.`,
    ],
    "secao-recorrencia": [
      `${sentenceStart(weekday.label)} apresenta a maior recorrência semanal, com ${weekday.value} dos intervalos sob restrição. ${sentenceStart(secondWeekday.label)} aparece em seguida, com ${secondWeekday.value}, permitindo comparar os dois dias mais expostos.`,
      `Ao longo do dia, o pico ocorre às ${hour.label}, com ${hour.value}. O segundo horário de maior recorrência é ${secondHour.label}, com ${secondHour.value}, delimitando a faixa do dia em que os cortes mais se concentraram.`,
      `A combinação entre dia e horário ajuda a refinar uma semana destacada pela previsão. Dentro de uma mesma janela, a usina pode comparar períodos historicamente mais expostos com períodos em que a geração tende a permanecer disponível.`,
      `Essa leitura torna a previsão mais acionável: a semana indica onde olhar, enquanto o perfil diário ajuda a escolher o momento da intervenção com menor conflito entre manutenção e produção.`,
    ],
    "secao-qualidade": [
      `${simultaneous} dos registros também aparecem em outras usinas ou conjuntos do ponto, enquanto ${exclusive} aparecem somente neste ativo. A diferença mostra quanto do padrão observado foi compartilhado no ponto de conexão.`,
      `${formatEvidence(quality.coverage.value, quality.coverage.unit)} do histórico esperado está disponível para a análise. A atualização apresenta ${formatEvidence(quality.delay.value, quality.delay.unit)} de defasagem, indicando quão recente é a base usada para interpretar o padrão.`,
      `${formatEvidence(quality.nullRate.value, quality.nullRate.unit)} dos registros possuem informação ausente e ${formatEvidence(quality.duplicates.value, quality.duplicates.unit)} aparecem repetidos. Esses indicadores mostram quanto tratamento foi necessário antes de comparar períodos e ativos.`,
      `Cobertura alta, baixa ausência e atualização recente aumentam a consistência da leitura. Esses indicadores também permitem que a usina veja quando uma nova atualização alterou o padrão usado na previsão e no ranking de janelas.`,
    ],
  };
}
