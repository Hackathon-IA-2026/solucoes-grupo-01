# Auditoria da probabilidade e da granularidade ONS

## Defeito confirmado

A versão anterior classificava como evento qualquer dia com `curtailment_mwh > 0`. Para Rio do Vento, a previsão publicada variava de 99,7246% a 100%, com média de 99,8191%. A calibração Platt aumentava probabilidades brutas já altas e não tinha caminhos independentes suficientes para sustentar a calibração.

## Correção aplicada

O evento previsto passou a significar um dia cuja estimativa de energia restringida alcança ou supera o percentil 75 do histórico do próprio conjunto gerador. O limiar de Rio do Vento é 1.962,0995 MWh/dia. A probabilidade usa apenas taxas empíricas calculadas no histórico mensal, nos últimos 30 dias, nos últimos sete dias e no dia anterior. A calibração Platt foi desativada.

A energia esperada passou a ser calculada separadamente da probabilidade do evento alto. A fórmula usa 45% da média histórica do mês, 25% da média móvel de 30 dias, 20% da média móvel de sete dias e 10% do dia anterior. A previsão recursiva usa somente valores disponíveis antes de cada data prevista.

A probabilidade empírica continua no artefato para auditoria, mas foi retirada da interface porque o backtest mostra deriva temporal e Brier alto. A interface apresenta energia restringida estimada em MWh/dia, faixa de incerteza e janelas de maior volume estimado.

## Resultado regenerado

| Conjunto ONS | Limiar P75 (MWh/dia) | Prob. mínima | Prob. média | Prob. máxima | Brier no teste | Taxa de evento no teste | MAE modelo (MWh/dia) | Melhor baseline (MWh/dia) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Rio do Vento | 1.962,0995 | 35,7472% | 47,2668% | 55,7741% | 0,267678 | 94,1667% | 1.365,293905 | 1.440,298871 |
| Laranjeiras | 1.511,209875 | 18,1855% | 26,7337% | 33,5451% | 0,217533 | 96,1111% | 921,058129 | 924,562755 |
| Serra da Babilônia | 958,88525 | 20,1644% | 29,7293% | 37,2411% | 0,233440 | 94,1667% | 582,684453 | 555,774635 |
| Monte Verde Solar | 547,11475 | 25,1538% | 34,4666% | 54,2216% | 0,266799 | 89,5833% | 307,712641 | 293,509492 |
| Luzia | 114,452625 | 23,9737% | 31,8813% | 43,7773% | 0,372529 | 86,2500% | 126,519999 | 122,785893 |

Os resultados negativos permanecem visíveis. O modelo supera a melhor baseline em Rio do Vento e Laranjeiras, mas perde em Serra da Babilônia, Monte Verde Solar e Luzia. A previsão continua demonstrativa e não sustenta uma afirmação de desempenho operacional.

## Granularidade dos ativos

Os códigos `CJU_*` identificam conjuntos geradores, não usinas individuais. A base pública de energia restringida usada pelo produto publica a medida nesse nível agregado.

A análise por conjunto descrita neste documento foi substituída por uma análise por usina individual na rota `/exposicao`. A base detalhada publica o indicador de restrição por usina e a geração verificada, mas não publica a energia restringida apurada por usina. A energia individual passou a ser um proxy reconciliado com o total publicado do conjunto, com rateio pela perda potencial e fallback de capacidade apenas entre usinas restritas. A ocorrência usa `flg_geracaorestrita` da própria usina. O método, a conservação e os resultados por usina estão em `docs/audits/2026-09-27-granularidade-por-usina-e-narrativas-ia.md`.

A interface deixou de identificar cada opção como conjunto gerador. O seletor da Exposição mostra exatamente cinco usinas individuais verificadas, uma por contexto atual: `RNEM13` (Ventos de Santa Martina 13), `BAEA52` (Assuruá 5 II), `BAEB0B` (Serra da Babilônia B), `RNMVS2` (Monte Verde Solar II) e `PBLZ3` (Luzia 3). Cada opção informa o conjunto ONS e o ponto de conexão como contexto. Nenhum identificador `CJU_*` é selecionável.

## Relação com os resultados de probabilidade

A tabela de probabilidade e a tabela de erro desta auditoria pertencem ao artefato por conjunto gerador da etapa anterior, com o alvo de dia restrito definido no nível agregado. O backtest por usina individual, com alvo próprio, métricas por usina e guardas de suporte e saturação, está na auditoria por usina. Os resultados negativos continuam visíveis nos dois artefatos.

## Reprodutibilidade

O gerador por conjunto foi executado duas vezes consecutivas com resultados idênticos.

- SHA-256 registrado pelo gerador por conjunto: `642c34eb14099c0a2e8f962794d4962f8c38c0bf3dfb012a3492d0e452997cf0`
- O relatório Markdown daquela execução não está empacotado neste repositório; seu hash histórico não é usado como gate atual.
- Ativos: 5
- Linhas previstas: 300
- Datas únicas: 60

O artefato por usina individual é reprodutível pelos mesmos comandos documentados na auditoria por usina. Digests empacotados: catálogo `f1f899744a23948c91eda061d0c755aa8a47d61344dac046eb945c6924e9176d`, histórico `bf8a1a105c6cc1db3a22b0d295b5d1496f981f33dc069290023a3eb6ab911cd2` e previsão `07441ead594b942ca18f7d38b329c862a62799a58fe92f902da4fbdd5741c15b`.
