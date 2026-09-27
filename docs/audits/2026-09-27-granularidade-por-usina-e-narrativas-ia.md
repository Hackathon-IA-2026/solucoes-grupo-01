# Auditoria da granularidade por usina e das narrativas de IA

Documento técnico da implementação que substituiu a análise por conjunto gerador (`CJU_*`) por uma análise de usinas individuais na rota `/exposicao`. Todos os valores foram reextraídos dos artefatos empacotados em `backend/src/curtailess/data/` e do código confirmado até os commits `e77d6a5` e `fbf1323`. Nenhum número foi copiado de memória.

## 1. Natureza dos resultados

Os resultados de estado, previsão, alívio e risco são possibilidades demonstrativas concretas produzidas por simulação determinística a partir de dados públicos. Eles não são telemetria privada, não são leitura de Supervisory Control and Data Acquisition (SCADA), não são limite físico confirmado, não são aprovação, validação ou coordenação do Operador Nacional do Sistema Elétrico (ONS) e não representam coordenação real de operação ou de manutenção entre agentes. As agendas de manutenção são simuladas. A energia das demais entidades do ponto nunca é apresentada como energia da usina selecionada.

## 2. Fontes

Fontes públicas do ONS lidas pelos materializadores:

- `restricao_coff_eolica_tm` e `restricao_coff_fotovoltaica_tm`: base agregada por conjunto gerador, usada como total de controle da energia restringida.
- `restricao_coff_eolica_detail_tm` e `restricao_coff_fotovoltaica_detail_tm`: base detalhada de meia hora por usina, com `flg_geracaorestrita` e geração verificada, usada para ocorrência e para as curvas individuais.
- `usina_conjunto`: vínculo entre usina individual e conjunto gerador, com vigência.
- `capacidade-geracao`: potência efetiva cadastrada das unidades geradoras.
- Meteorologia: rodada curta arquivada, sinal sazonal de 60 dias e climatologia mensal ERA5, mais a climatologia da própria usina.

Artefatos empacotados e seus SHA-256:

| Artefato | Caminho | SHA-256 |
|---|---|---|
| Catálogo de usinas | `data/individual_plant_catalog.json` | `f1f899744a23948c91eda061d0c755aa8a47d61344dac046eb945c6924e9176d` |
| Histórico individual | `data/individual_plant_history.json` | `bf8a1a105c6cc1db3a22b0d295b5d1496f981f33dc069290023a3eb6ab911cd2` |
| Previsão individual | `data/individual_plant_forecast.json` | `fb163f1960cb3869a0e25edf30644171a1ae8410903290ef43d411d28ee54f54` |
| Agenda simulada do ponto | `data/simulated_point_maintenance_schedule.json` | `a66c476933c4ab51fa06ce41a37feaa9fc1f34ef8509779850a52dd5f6ed515d` |

O `input_manifest` do artefato de previsão declara o digest consolidado `58e9efc5a1f53f0f6eb6403e6f6f4ac36dba932646d676fe729963994ad12dc1` sobre catálogo, histórico, vínculo, capacidade, agregados e detalhados.

Janelas usadas:

- Histórico: `2024-04-01` a `2026-09-25`, 908 dias de calendário, corte em `2026-09-25 23:30:00`.
- Previsão: `2026-09-26` a `2026-11-24`, 60 dias consecutivos.

Código responsável: `tools/build_individual_plant_cohort.py`, `plant_exposure_history.py`, `plant_exposure_forecast.py`, `point_exposure_simulation.py`, `exposure_view.py`, `exposure_narrative.py`, `exposure_narrative_repository.py`, `materialize_exposure_narratives.py`, `exposure_forecast_import.py`.

## 3. Seleção fixa das cinco usinas

A coorte tem exatamente cinco usinas individuais, uma por contexto atual. A seleção prioriza, nesta ordem: vínculo cadastral inequívoco e vigente, cobertura histórica, cobertura da variável meteorológica e completude da capacidade cadastrada. Um vínculo ambíguo ou inativo não é selecionável, e a materialização falha com relatório de candidatas em vez de inventar uma usina. `CJU_*` nunca é selecionável.

| `asset_id` | Nome | Tec. | UF | Conjunto | Ponto | MW | CEG | Vigência | Candidatas | Cobertura | Dias restritos | Unidades |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `RNEM13` | Ventos de Santa Martina 13 | wind | RN | `CJU_RNRDV` Rio do Vento | `RNCMM-500-A` | 67.2 | `EOL.CV.RN.038322-8.01` | desde 2021-06-30 | 8 | 100.00% (908 d) | 79.9559% | 3 |
| `BAEA52` | Assuruá 5 II | wind | BA | `CJU_BALRA` Laranjeiras | `BAGOR-230-A` | 46.4 | `EOL.CV.BA.051785-2.01` | desde 2022-12-02 | 14 | 100.00% (908 d) | 81.2775% | 2 |
| `BAEB0B` | Serra da Babilônia B | wind | BA | `CJU_BASDB` Serra da Babilônia | `BAMPD-230-A` | 31.8 | `EOL.CV.BA.040608-2.01` | desde 2021-03-19 | 14 | 100.00% (908 d) | 80.1762% | 2 |
| `RNMVS2` | Monte Verde Solar II | solar | RN | `CJU_RNMVS` Monte Verde Solar | `RNMTV-500-A` | 42.48 | `UFV.RS.RN.045154-1.01` | desde 2023-12-15 | 5 | 100.00% (908 d) | 63.2159% | 2 |
| `PBLZ3` | Luzia 3 | solar | PB | `CJU_PBLZA` Luzia | `RNSTL-500-A` | 58.95 | `UFV.RS.PB.044470-7.01` | desde 2022-05-27 | 2 | 100.00% (908 d) | 57.0485% | 3 |

A capacidade é a soma da potência efetiva cadastrada das unidades ativas. A cobertura histórica é contada na base detalhada de meia hora. O ponto de conexão é o publicado no nível do conjunto, não uma medida por usina. Cada usina declara conjunto, CEG e vigência; a interface usa apenas o `asset_id` individual.

## 4. Evento de restrição individual

O evento histórico de ocorrência é definido por usina e por dia:

```text
plant_curtailed_day = 1 quando existe ao menos um intervalo válido de 30 minutos
com flg_geracaorestrita = 1 para a usina no dia; caso contrário, 0.
```

Intervalos inválidos, duplicados e com flag de dado inválido são excluídos antes da contagem. O alvo usa o indicador detalhado da própria usina, nunca a geração verificada, a disponibilidade ou o fator de capacidade do intervalo previsto. A frequência de dias restritos no período é 79.9559% (`RNEM13`), 81.2775% (`BAEA52`), 80.1762% (`BAEB0B`), 63.2159% (`RNMVS2`) e 57.0485% (`PBLZ3`).

## 5. Energia individual, rateio e conservação

A energia individual é um proxy reconciliado, não uma medição direta do ONS. Por intervalo válido:

```text
raw_loss_i,t = max(0, generation_potential_i,t - generation_accepted_i,t)
weight_i,t = raw_loss_i,t / sum(raw_loss_j,t) para usinas restritas com proxy válido
allocated_curtailment_i,t = group_curtailment_t * weight_i,t
```

`generation_potential` vem da curva da própria usina, treinada somente em intervalos sem restrição. `generation_accepted` é a geração verificada no intervalo. A diferença só é usada quando o indicador detalhado marca restrição.

Fallback de rateio: quando os proxies individuais não sustentam pesos, o peso passa a ser a participação da capacidade, aplicada somente entre as usinas marcadas como restritas. Se nenhuma usina tiver indicação válida, o total do conjunto permanece não alocado. O total nunca é distribuído silenciosamente por todas as usinas.

Conservação do total publicado do conjunto na janela:

| Medida | Valor |
|---|---|
| Total público dos cinco conjuntos | 3.155.888,206 MWh |
| Total alocado às usinas | 3.155.888,206 MWh |
| Tolerância | 1e-6 MWh |
| Resíduo máximo observado | 9,094947017729282e-13 MWh |

Totais por conjunto e método de rateio:

| Conjunto | Ponto | Usinas | MWh público | Cobertura | proxy de perda | fallback de capacidade | sem restrição |
|---|---|---|---|---|---|---|---|
| `CJU_RNRDV` | `RNCMM-500-A` | 8 | 1.235.868,0235 | 100.0% | 712 | 2 | 194 |
| `CJU_BALRA` | `BAGOR-230-A` | 14 | 977.121,2935 | 100.0% | 738 | 0 | 170 |
| `CJU_BASDB` | `BAMPD-230-A` | 14 | 599.237,878 | 100.0% | 706 | 1 | 201 |
| `CJU_RNMVS` | `RNMTV-500-A` | 5 | 266.906,552 | 100.0% | 538 | 14 | 356 |
| `CJU_PBLZA` | `RNSTL-500-A` | 2 | 76.754,459 | 100.0% | 464 | 20 | 424 |

Energia restringida atribuída à usina selecionada na janela: `RNEM13` 163.936,650127 MWh, `BAEA52` 94.987,325407 MWh, `BAEB0B` 45.700,262026 MWh, `RNMVS2` 63.653,877533 MWh e `PBLZ3` 30.854,070485 MWh. Cobertura de alocação 100.0% em todas.

O contexto do ponto agrega somente os conjuntos publicados naquele ponto. Cada conjunto aparece em um único ponto e é contado uma única vez. Totais: 5 pontos, 24 conjuntos, 11.907.777,4095 MWh públicos no ponto. Nenhum total de conjunto é somado de novo quando o contexto é derivado das usinas.

## 6. Telemetria simulada e capacidade operacional estimada

A capacidade instalada continua ancorada no cadastro. A capacidade operacional disponível é estimada pela simulação da usina, e a capacidade de injeção aceita é estimada a partir da condição simulada da usina, do conjunto e de todas as entidades do ponto. Estado simulado no corte:

| Usina | Geração (MW) | Potencial (MW) | Disponibilidade (MW) | Cap. operacional (MW) | Limite aceito (MW) | Restringido (MW) | Meteorologia |
|---|---|---|---|---|---|---|---|
| `RNEM13` | 28,505609 | 36,079957 | 65,524966 | 65,524966 | 28,505609 | 7,574348 | 27,000153 m/s |
| `BAEA52` | 20,334644 | 24,727117 | 45,234263 | 45,234263 | 20,334644 | 4,392473 | 0,857479 m/s |
| `BAEB0B` | 14,018772 | 17,48511 | 28,988428 | 31,003768 | 14,018772 | 3,466338 | 2,559117 m/s |
| `RNMVS2` | 9,309651 | 12,412868 | 41,417207 | 41,417207 | 9,309651 | 3,103217 | 1055,894953 W/m2 |
| `PBLZ3` | 17,56431 | 21,17725 | 55,6107 | 57,478741 | 17,56431 | 3,61294 | 276,996595 W/m2 |

Toda a telemetria simulada das usinas ligadas ao ponto é considerada na pressão sistêmica, mesmo quando apenas uma das cinco usinas está selecionada. A correlação meteorológica espacial entre usinas próximas é preservada.

## 7. Contexto do ponto e envelope de geração aceita

```text
available_generation_j_t = potential_generation_j_t * availability_j_t * maintenance_derate_j_t
generation_potential_point_t = sum(available_generation_j_t for j in point)
point_excess_t = max(0, generation_potential_point_t - accepted_point_envelope_t)
```

| Ponto | Entidades | Cap. instalada (MW) | Potencial (MW) | Envelope aceito (MW) | Excesso (MW) | Intercepto (MW) | Inclinação |
|---|---|---|---|---|---|---|---|
| `RNCMM-500-A` | 16 | 1.038,2 | 583,075017 | 449,451485 | 115,73963 | 373,880139 | 0,35 |
| `BAGOR-230-A` | 52 | 1.831,1 | 901,56071 | 723,843758 | 152,066209 | 221,256767 | 0,65 |
| `BAMPD-230-A` | 44 | 1.319,55086 | 637,896809 | 527,25599 | 89,860468 | 87,297847 | 0,75 |
| `RNMTV-500-A` | 43 | 1.324,98226 | 55,280729 | 40,806345 | 13,602115 | 0,0 | 0,75 |
| `RNSTL-500-A` | 67 | 2.296,028 | 141,728211 | 118,353646 | 20,885937 | 0,0 | 0,85 |

## 8. Envelope operacional estimado e sua limitação

```text
envelope = min(potential, intercept + slope * potential), com slope em [0, 1]
```

O envelope é ajustado por mínimos quadrados ao curtailment publicado do ponto. Ele é uma estimativa construída a partir de dados públicos e de simulação. Não é limite físico confirmado, não é restrição operacional real e não é decisão do ONS. A usina selecionada é comparada a esse envelope estimado, e o texto da interface trata o resultado como possibilidade demonstrativa.

### 8.1 Correção de fonte duplicada e de granularidade tecnológica (commit `fbf1323`)

Duas causas degeneraram o envelope dos pontos solares antes da correção:

1. Fonte duplicada. A mesma base agregada podia ser passada para as duas tecnologias. Ler o mesmo arquivo duas vezes somava o mesmo conjunto duas vezes e inflava o curtailment publicado. A leitura agora resolve cada caminho com `glob` e mantém um conjunto `seen`, lendo cada arquivo uma única vez.
2. Granularidade tecnológica. A série de potencial contém apenas as usinas com curva sob a coluna meteorológica do ponto, ou seja, as usinas da tecnologia do ponto. Um ponto de conexão pode hospedar conjuntos de ambas as tecnologias. Somar o curtailment publicado dos conjuntos da outra tecnologia comparava grandezas não equivalentes e empurrava o ajuste para `(0, 0)`, resultando em envelope aceito zero e 100% de curtailment para a usina solar selecionada. A série publicada passou a ser restrita aos conjuntos cujas usinas estão efetivamente representadas no potencial.

Resultado corrigido dos pontos solares:

| Ponto | Envelope antes | Envelope depois | Envelope aceito depois (MW) |
|---|---|---|---|
| `RNMTV-500-A` | intercepto 0,0, inclinação 0,0 | intercepto 0,0, inclinação 0,75 | 40,806345 |
| `RNSTL-500-A` | intercepto 0,0, inclinação 0,0 | intercepto 0,0, inclinação 0,85 | 118,353646 |

Efeito nos MWh esperados de 60 dias das usinas solares: `PBLZ3` caiu de 29.756,008 MWh para 4.463,401 MWh e `RNMVS2` caiu de 17.874,531 MWh para 4.468,633 MWh. O envelope aceito acumulado passou de 0,0 MWh para 25.292,607 MWh (`PBLZ3`) e 13.405,898 MWh (`RNMVS2`). O envelope aceito zero era o sintoma do ajuste degenerado e não uma restrição real.

## 9. Cenários com e sem manutenção, alívio e curtailment evitado

As usinas participantes do ponto têm agendas simuladas geradas de forma determinística. Cada janela tem `derate` 0,35 nos intervalos agendados. `maintenance_derate_j_t` é 1 sem manutenção e cai conforme a indisponibilidade agendada. Contagem de janelas e de usinas por ponto:

| Ponto | Usinas | Janelas simuladas | Usina candidata |
|---|---|---|---|
| `RNCMM-500-A` | 16 | 11 | `RNEM13` |
| `BAGOR-230-A` | 52 | 36 | `BAEA52` |
| `BAMPD-230-A` | 44 | 25 | `BAEB0B` |
| `RNMTV-500-A` | 43 | 33 | `RNMVS2` |
| `RNSTL-500-A` | 67 | 47 | `PBLZ3` |

Cada previsão calcula dois cenários determinísticos sobre as mesmas amostras meteorológicas: cenário sem as manutenções agendadas e cenário com as manutenções agendadas. A diferença produz alívio da rede em MW, MWh de curtailment evitados e redução do risco em pontos percentuais. Um terceiro contrafactual aplica a janela candidata da usina selecionada e mede o efeito de retirá-la por 72 horas.

Semântica exata dos campos:

- `scheduled_maintenance_relief_mwh`: diferença de MWh da usina selecionada entre o cenário sem manutenção e o cenário com manutenções agendadas.
- `avoided_curtailment_mwh`: diferença do excesso do ponto entre o cenário sem manutenção e o cenário com manutenções agendadas.
- `candidate_maintenance_relief_mwh`: diferença de MWh da usina selecionada entre o cenário com manutenções agendadas e o contrafactual da janela candidata.
- `risk_reduction_percentage_points`: redução da probabilidade de evento do cenário com manutenção frente ao cenário sem manutenção.

Totais acumulados de 60 dias:

| Usina | Esperado (MWh) | Alívio da manutenção agendada (MWh) | Curtailment evitado no ponto (MWh) |
|---|---|---|---|
| `RNEM13` | 10.907,060 | 661,411 | 16.024,052 |
| `BAEA52` | 6.325,162 | 162,428 | 12.774,444 |
| `BAEB0B` | 3.382,071 | 319,542 | 7.466,034 |
| `RNMVS2` | 4.468,633 | 0,0 | 314,017 |
| `PBLZ3` | 4.463,401 | 110,885 | 537,544 |

Os cenários com e sem manutenção reutilizam as mesmas amostras meteorológicas, de modo que a diferença representa apenas a indisponibilidade planejada. O produto apresenta mitigação como resultado do cenário, não como coordenação real entre agentes nem como compromisso operacional das usinas.

## 10. Janelas críticas de 72 horas

O motor trabalha com a série subdiária de 30 minutos e avalia todas as janelas móveis de exatamente 72 horas, equivalentes a 144 intervalos consecutivos. Para cada cenário `s` e janela `w`:

```text
curtailed_mwh_s_w = sum(curtailed_mw_s_t * 0.5 for t in w)
window_expected_mwh_w = mean(curtailed_mwh_s_w for s in scenarios)
window_probability_w = mean(curtailed_mwh_s_w > 0 for s in scenarios)
```

As três janelas são ordenadas primeiro por `window_expected_mwh` e depois por `window_probability`. Após selecionar uma janela, todas as candidatas que se sobrepõem a ela são removidas. Não há agrupamento semanal. Cada janela tem 144 intervalos e 72,0 horas.

| Usina | Rank | Início | Fim | Esperado (MWh) | Prob. | Alívio agendado (MWh) | Evitado no ponto (MWh) | Alívio candidato (MWh) |
|---|---|---|---|---|---|---|---|---|
| `RNEM13` | 1 | 2026-10-07 | 2026-10-09 | 1316,868596 | 1,0 | 0,0 | 0,0 | 882,052253 |
| `RNEM13` | 2 | 2026-10-15 | 2026-10-17 | 1245,708989 | 1,0 | 49,05193 | 1270,93951 | 0,0 |
| `RNEM13` | 3 | 2026-10-04 | 2026-10-06 | 1223,679689 | 1,0 | 23,922025 | 622,781501 | 0,0 |
| `BAEA52` | 1 | 2026-10-12 | 2026-10-14 | 651,398783 | 1,0 | 14,089133 | 1219,342314 | 420,904677 |
| `BAEA52` | 2 | 2026-10-15 | 2026-10-17 | 639,385424 | 1,0 | 5,6218 | 491,331841 | 0,0 |
| `BAEA52` | 3 | 2026-10-05 | 2026-10-07 | 612,94101 | 1,0 | 28,439826 | 2318,052162 | 0,0 |
| `BAEB0B` | 1 | 2026-10-12 | 2026-10-14 | 373,124916 | 1,0 | 2,65736 | 311,574099 | 240,443681 |
| `BAEB0B` | 2 | 2026-10-04 | 2026-10-06 | 362,008884 | 1,0 | 9,883822 | 1116,02996 | 0,0 |
| `BAEB0B` | 3 | 2026-10-07 | 2026-10-09 | 347,63954 | 1,0 | 11,188414 | 1241,617011 | 0,0 |
| `RNMVS2` | 1 | 2026-09-26 | 2026-09-28 | 344,266675 | 1,0 | 0,0 | 0,0 | 179,557685 |
| `RNMVS2` | 2 | 2026-10-07 | 2026-10-09 | 299,953188 | 1,0 | 0,0 | 0,0 | 0,0 |
| `RNMVS2` | 3 | 2026-10-14 | 2026-10-16 | 293,362736 | 1,0 | 0,0 | 0,0 | 0,0 |
| `PBLZ3` | 1 | 2026-11-05 | 2026-11-07 | 241,060336 | 1,0 | 0,0 | 139,560622 | 113,379449 |
| `PBLZ3` | 2 | 2026-11-19 | 2026-11-21 | 240,617204 | 1,0 | 0,0 | 0,0 | 0,0 |
| `PBLZ3` | 3 | 2026-11-12 | 2026-11-14 | 240,190017 | 1,0 | 0,0 | 0,0 | 0,0 |

## 11. Contrato dos 60 pontos diários e gráfico em linha

O backend entrega exatamente 60 pontos diários ordenados e sem lacunas, no intervalo `2026-09-26` a `2026-11-24`. Cada ponto contém:

- `forecast_date` ISO e `display_label` no formato `DD/MM`;
- `expected_curtailed_mwh`, `lower_mwh` e `upper_mwh`, com `lower <= expected <= upper`;
- `curtailment_probability` entre 0 e 1;
- `potential_generation_mwh`, `accepted_generation_envelope_mwh`;
- `scheduled_maintenance_relief_mwh`, `avoided_curtailment_mwh`, `risk_reduction_percentage_points`;
- `weather_value`, `weather_unit` e `weather_source`.

A interface usa gráfico em linha com marcador e label em todos os 60 dias. O tooltip mostra data completa, MWh esperados e risco em porcentagem. A faixa de incerteza aparece como área sombreada. Em telas estreitas o gráfico permite rolagem horizontal para preservar os 60 labels sem criar overflow na página. Não há gráfico de barras.

## 12. Probabilidade, severidade e backtest por usina

A probabilidade responde à ocorrência de restrição e os MWh respondem à severidade. As duas quantidades são calculadas separadamente e nunca multiplicadas.

- Probabilidade: regressão logística temporal sobre taxas históricas da própria usina, sazonalidade, defasagens com `shift(1)`, pressão das demais usinas do ponto e normal climatológica da meteorologia. Taxas de mês, dia da semana e janelas recentes passam por encolhimento empírico em direção à taxa base.
- Severidade: simulação de meia hora de todas as usinas ativas do ponto contra o envelope de geração aceita estimado, com três cenários de manutenção sobre as mesmas amostras meteorológicas.

O backtest é temporal e recursivo, com corte cronológico e sem embaralhamento: 540 dias de treino, 120 de validação e 240 de teste. A seleção de modelo, regularização e calibração é congelada nos caminhos de validação; o teste apenas reporta o desempenho da escolha já congelada. A calibração só é aceita quando melhora o Brier e não piora a confiabilidade.

Métricas de backtest por usina (valores no teste, exceto onde indicado):

| Usina | Brier calibrado (teste) | Melhor baseline (teste) | Baseline | Taxa de evento (teste) | MAE modelo (MWh/dia) | MAE baseline (MWh/dia) | Cobertura do intervalo |
|---|---|---|---|---|---|---|---|
| `RNEM13` | 0,137228 | 0,120833 | persistência | 89,1667% | 300,507064 | 168,992564 | 71,25% |
| `BAEA52` | 0,085998 | 0,1125 | persistência | 91,25% | 580,104433 | 97,770275 | 42,9167% |
| `BAEB0B` | 0,104584 | 0,1375 | persistência | 89,5833% | 436,282278 | 40,91076 | 54,1667% |
| `RNMVS2` | 0,07949 | 0,1125 | persistência | 91,25% | 60,28536 | 64,889642 | 55,0% |
| `PBLZ3` | 0,122505 | 0,145833 | persistência | 86,25% | 129,73213 | 62,04345 | 22,5% |

O baseline mais forte incluindo constantes é a persistência, com Brier na validação de 0,041667 (`RNEM13`, `BAEA52`, `BAEB0B`), 0,025 (`RNMVS2`) e 0,091667 (`PBLZ3`). O modelo calibrado supera o baseline mais forte na validação em todas as cinco usinas (`beats_baseline` verdadeiro), mas o resultado negativo de severidade permanece visível: o erro absoluto médio do modelo é maior que o do baseline em quatro das cinco usinas. A energia não é obtida por `probabilidade * severidade`.

Probabilidade publicada. A política é congelada na validação com guardas de suporte e saturação. Em todas as cinco usinas, a série publicada de 60 dias é o baseline de frequência histórica (`probability_source = baseline_frequency`, `probability_status = baseline_historical_frequency`), com valor constante igual à taxa histórica: `RNEM13` 0,799559, `BAEA52` 0,812775, `BAEB0B` 0,801762, `RNMVS2` 0,632159 e `PBLZ3` 0,570485. As fontes inelegíveis para o horizonte foram descartadas pelos guardas:

- `baseline_persistence`: a série de 60 dias ficou inteiramente acima de 95%, saturada.
- `model_calibrated`: a calibração foi ajustada numa faixa de probabilidade que não cobre o horizonte; aplicá-la seria extrapolação.
- `model_raw`: a trajetória futura sai do suporte de probabilidade congelado na validação.

Validação estrita de suporte. Um modelo publicado não pode ter qualquer dia fora do suporte de probabilidade congelado nos caminhos de validação usados na seleção. Uma série publicada com os 60 dias acima de 95% falha a materialização. Verificações do artefato: todas as usinas têm pelo menos um dia abaixo de 95%, nenhuma série publicada está saturada, todas estão dentro do suporte validado e há 0 dias fora do suporte nas séries publicadas. São 5 usinas e 5 pontos.

## 13. Transição da previsão meteorológica para cenários climatológicos

A rodada curta de meteorologia cobre `GFS_HORIZON_DAYS = 16` dias. Dentro desse horizonte, a previsão usa a rodada arquivada e o sinal sazonal. Além dele, a previsão combina climatologia da localização, sazonalidade da usina e cenários meteorológicos amostrados, com incerteza crescente. Parâmetros: peso do sinal sazonal 0,5, peso do sinal além do horizonte 0,5, inflação semanal de incerteza 0,08 e dispersão relativa da climatologia 0,18.

`weather_source` por usina: `gfs_seas5_era5` para `RNEM13`, `BAEA52`, `BAEB0B` e `RNMVS2`; `ons_plant_climatology` para `PBLZ3`, cujo ponto não tem coordenadas meteorológicas publicadas e usa apenas a climatologia da própria usina. A meteorologia histórica vem da própria usina. Não há snapshots históricos de emissão de previsão meteorológica, por isso o backtest mede ocorrência e severidade sem a previsão meteorológica do dia. A narrativa não trata datas distantes como certeza operacional.

## 14. Narrativas de IA por seção

Cada seção recebe somente seu subconjunto de evidências. Uma única chamada Bedrock Converse cobre as seis seções, com `maxTokens` explícito (1600) e retry adaptativo, sem `temperature` e sem ferramentas. O modelo não recebe rótulos internos de procedência e não pode escrever diretamente em armazenamento.

Chaves exatas: `secao-ativo`, `secao-resumo`, `secao-previsao`, `secao-razao-origem`, `secao-recorrencia`, `secao-qualidade`.

Validação por seção. O texto de cada seção é validado somente contra a evidência daquela seção. A validação rejeita:

- JSON inválido, chave ausente ou desconhecida e parágrafo fora dos limites;
- número que não seja exatamente um número exposto pela evidência da seção, comparado em `Decimal` sem arredondamento;
- alteração de unidade, com unidade reconhecida em fronteira alfanumérica;
- identificador que não exista na evidência;
- rótulos internos de procedência e termos técnicos proibidos;
- afirmações proibidas: causalidade não suportada, aprovação, validação ou coordenação do ONS, telemetria privada ou SCADA, limite físico confirmado, capacidade confirmada, certeza sobre o futuro e recomendação de manutenção ou bateria. Frases negadas são aceitas.

Política de fallback e cache por seção:

1. Uma seção Bedrock válida é aceita; uma seção inválida cai para o fallback determinístico sem descartar as cinco seções válidas.
2. Se todas as seções caírem, o resultado é o fallback determinístico e nenhum `model_id` é registrado.
3. Uma resposta ilegível do modelo não é problema de transporte, então o fallback determinístico é aplicado imediatamente, sem tentar outro modelo.
4. Falha de transporte tenta os modelos primário, de fallback e de emergência em ordem, com `Config(retries={"max_attempts": 5, "mode": "adaptive"})`.
5. O fallback determinístico consome o mesmo pacote de evidências e não expõe rótulos de procedência.

Persistência e leitura:

- `NARRATIVE_SCHEMA_VERSION = "exposure-narrative-v2"`.
- Chave consolidada imutável: `VERSION#{schema_version}#{input_digest}`, particionada por `asset_id`.
- Chave imutável por seção: `SECTION#{schema_version}#{section_id}#{evidence_digest}`, também particionada por `asset_id`.
- Ponteiro corrente: partição `asset_id`, chave de ordenação `CURRENT`.
- Cada registro consolidado preserva os digests de evidência e conteúdo das seis seções. A gravação é condicional e idempotente; uma versão existente com conteúdo diferente é rejeitada. O ponteiro corrente só é atualizado depois das seções e da versão consolidada.
- Na leitura, a API resolve cada seção separadamente: tenta primeiro a seção com digest de evidência exato e depois a seção do ponteiro `CURRENT`, revalidada contra a evidência atual. Somente a seção ausente ou incompatível usa fallback determinístico; uma seção inválida não derruba as cinco válidas, as métricas ou os gráficos.
- O modo de geração (`bedrock`, `cached_bedrock`, `deterministic_fallback`) fica no contrato interno. A interface usa o título constante "Análise dos dados" e não distingue Bedrock, cache ou fallback. Erros técnicos nunca aparecem ao usuário.

Materialização explícita, sem agendamento:

```bash
uv run python -m curtailess.materialize_exposure_narratives --asset-id RNEM13
uv run python -m curtailess.materialize_exposure_narratives --all
```

A seleção é mutuamente exclusiva e obrigatória; sem `EXPOSURE_NARRATIVES_TABLE` configurada, o comando sai com código 2 e nenhuma chamada Bedrock é feita. A aba Manutenção não consome esta agenda e não há integração com Manutenção, Bateria ou Relatório.

## 15. Interface: sem procedência, sem chamada para ação

A superfície principal da Exposição não exibe nomes de fonte, métodos de ingestão, versões de dados, hashes, selos de calculado ou medido, períodos técnicos repetidos nem painel de procedência. A qualidade dos dados continua visível porque muda a leitura do resultado. A interface não mostra rótulos de procedência, método de simulação ou origem técnica. Não há chamada para ação no fim da Exposição, e a seleção da Exposição não contamina Manutenção, Bateria ou Relatório.

## 16. Reprodutibilidade

```bash
cd backend
uv run pytest -q tests/test_individual_plant_cohort.py tests/test_plant_exposure_history.py \
  tests/test_plant_exposure_forecast.py tests/test_point_exposure_simulation.py \
  tests/test_exposure_forecast_import.py tests/test_exposure_view.py \
  tests/test_exposure_narrative.py tests/test_exposure_narrative_repository.py
uv run python tools/build_individual_plant_cohort.py --help
uv run python -m curtailess.materialize_exposure_forecast --help
uv run python -m curtailess.materialize_exposure_narratives --help
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
cd ..
git diff --check
```

O gerador da coorte exige caminhos explícitos para detalhado eólico, detalhado solar, vínculo, capacidade, agregado eólico e agregado solar, com `--window-start`, `--window-end`, `--output` e `--report` opcionais. Nenhum deploy, chamada real ao Bedrock, escrita em DynamoDB ou importação para AWS faz parte desta auditoria.

## 17. Limites conhecidos

- A energia individual é proxy reconciliado, não medição direta do ONS.
- O backtest não usa a previsão meteorológica do dia por falta de snapshots históricos de emissão.
- A probabilidade publicada é um baseline declarado, não o modelo calibrado, por causa dos guardas de suporte e saturação.
- O erro de severidade do modelo é maior que o do baseline em quatro das cinco usinas.
- O envelope de geração aceita é estimado e ajustado a dados públicos, não é limite físico.
- A base detalhada solar omite `id_ons_conjuntousina` em parte de 2024; o vínculo foi recuperado pelo nome cadastral do conjunto.
- A série diária sustenta recorrência por dia da semana, não por horário.
- As agendas de manutenção são simuladas e não representam coordenação real.
