# Exposição por usina e narrativas de IA por seção

> **Para Hermes:** executar por checkpoints com até oito subagentes, incluindo revisões independentes nas etapas de forecast, backend, frontend e integração. O orquestrador deve verificar os resultados dos subagentes e reproduzir as métricas críticas antes de aceitá-las. Não executar deploy nem escrever em recursos AWS durante a implementação local.

**Objetivo:** substituir a análise por conjunto gerador por uma análise de usinas individuais, com histórico e previsão simulados a partir dos dados públicos do Operador Nacional do Sistema Elétrico (ONS), e apresentar uma interpretação gerada pelo Amazon Bedrock em cada uma das seis seções da tela Exposição.

**Arquitetura:** a demonstração analisará exatamente cinco usinas individuais, uma usina verificada para cada um dos cinco contextos atuais. A usina selecionada será a entidade principal da API e da interface. O conjunto gerador servirá para reconciliar a energia publicada pelo ONS entre suas usinas. Todas as usinas ligadas ao ponto de conexão terão telemetria simulada e serão consideradas na estimativa de pressão sistêmica. Os conjuntos serão agregações dessas usinas e não serão somados novamente. A simulação incluirá manutenções já agendadas por usinas participantes e recalculará o alívio da rede, o risco e os MWh com e sem essas indisponibilidades. A previsão meteorológica apoiará o horizonte em que estiver disponível, com cenários climatológicos no restante dos 60 dias. O forecast terá um ponto por dia, será exibido como gráfico em linha e produzirá três janelas críticas não sobrepostas de 72 horas. A previsão calculará separadamente a probabilidade de restrição e a severidade esperada em MWh. O Amazon Bedrock produzirá apenas parágrafos interpretativos validados contra os dados de cada seção.

**Tecnologias:** Python 3.12, FastAPI, Pydantic, boto3 Converse API, DynamoDB opcional para narrativas, React, TypeScript, Zod, Vitest, Playwright, AWS Serverless Application Model (SAM).

---

## 1. Escopo aprovado por este plano

A implementação ficará restrita à rota `/exposicao` e aos componentes, contratos, artefatos e testes usados por essa rota. As telas Manutenção, Bateria e Relatório continuarão usando seu estado demonstrativo isolado.

A implementação local não fará:

- deploy da stack;
- criação ou alteração efetiva de tabelas DynamoDB;
- importação de dados para AWS;
- chamadas reais ao Amazon Bedrock sem nova autorização;
- ativação do agendamento diário desabilitado no `template.yaml`;
- edição de `wireframe-v2/prototipo.html`;
- edição de `estrategia/modelagem-v5.md`;
- leitura ou escrita no Agent-Wiki ou na wikitica.

## 2. Decisões de produto e dados

### 2.1 Entidade principal

O `asset_id` exposto pela tela será o identificador individual da usina no ONS. Identificadores `CJU_*` não poderão aparecer como a entidade selecionável. Cada usina terá estes vínculos explícitos:

```json
{
  "asset_id": "RNEM01",
  "name": "nome público da usina",
  "entity_level": "plant",
  "ons_group_id": "CJU_RNRDV",
  "ons_group_name": "Rio do Vento",
  "connection_point": "RNCMM-500-A",
  "technology": "wind",
  "state": "RN",
  "capacity_mw": 0.0,
  "operational_data_status": "simulated"
}
```

A coorte inicial terá exatamente cinco usinas individuais, e não cinco conjuntos nem todas as usinas dos cinco conjuntos. Será escolhida uma usina verificada em cada contexto atual: Rio do Vento, Laranjeiras, Serra da Babilônia, Monte Verde e Luzia. A escolha priorizará, nesta ordem, vínculo cadastral inequívoco e vigente, cobertura histórica, disponibilidade das variáveis meteorológicas e completude da capacidade cadastrada. O script de materialização produzirá a classificação das candidatas e registrará por que cada usina foi selecionada. A materialização deverá verificar os vínculos nas bases detalhadas e cadastrais. Um nome ou identificador sem correspondência pública não será inventado. Se um dos contextos solares atuais não tiver uma usina verificável, a materialização falhará com um relatório de candidatas em vez de publicar uma usina fictícia.

### 2.2 Separação entre ocorrência e energia

A probabilidade responderá à pergunta “qual é a chance de esta usina sofrer alguma restrição neste dia?”. O alvo histórico será:

```text
plant_curtailed_day = 1 quando existe pelo menos um intervalo válido de 30 minutos
com flg_geracaorestrita = 1 para a usina no dia; caso contrário, 0.
```

A quantidade de energia responderá à pergunta “quantos MWh podem deixar de ser gerados por essa usina?”. Para cada intervalo válido de 30 minutos:

```text
raw_loss_i,t = max(0, generation_potential_i,t - generation_accepted_i,t)
```

No histórico, `generation_potential` será estimada pela curva da própria usina treinada somente em intervalos sem restrição. `generation_accepted` será a geração verificada no intervalo. A diferença será usada apenas quando o indicador detalhado marcar restrição.

A energia publicada no nível do conjunto será preservada como total de controle. O rateio será reconciliado por intervalo ou pelo menor período comum:

```text
weight_i,t = raw_loss_i,t / sum(raw_loss_j,t) para usinas restritas com proxy válido
allocated_curtailment_i,t = group_curtailment_t * weight_i,t
```

Quando os proxies individuais não sustentarem os pesos, o fallback será a participação da capacidade entre as usinas marcadas como restritas. Se nenhuma usina tiver indicação válida, o valor do conjunto permanecerá não alocado. A implementação nunca distribuirá silenciosamente o total por todas as usinas.

A soma dos valores individuais alocados deverá coincidir com o total público do conjunto dentro de uma tolerância numérica definida nos testes.

### 2.3 Telemetria simulada, capacidade e meteorologia

A demonstração tratará a telemetria simulada de cada usina como entrada disponível e internamente coerente. O pacote simulado incluirá geração atual, geração potencial, disponibilidade, capacidade operacional disponível, vento ou irradiância, limite operacional estimado, geração aceita, energia potencialmente restringida e estado de restrição. Esses valores alimentarão as seis seções, o cálculo histórico individual, o forecast e a narrativa.

A capacidade instalada continuará ancorada no cadastro da usina. A capacidade operacional disponível será estimada pela simulação da usina. A capacidade de injeção aceita será estimada a partir da condição simulada da usina, do conjunto e de todas as entidades ligadas ao ponto. O modelo comparará a geração potencial com o envelope operacional estimado de geração aceita:

```text
expected_curtailed_mwh_i,d =
    sum_t 0.5 * max(0, predicted_potential_mw_i,t - estimated_accepted_envelope_mw_i,t)
```

As previsões meteorológicas entrarão como features. Para o horizonte coberto pelo fornecedor pesquisado, serão usados vento em alturas compatíveis, irradiância, temperatura, quantis e ensembles disponíveis. O backtest usará previsões históricas arquivadas com `issued_at`, sem usar reanálise futura como se estivesse disponível no momento da decisão. Além do horizonte meteorológico útil, atualmente de até aproximadamente 16 dias na fonte pesquisada, o forecast de 60 dias combinará climatologia da localização, sazonalidade da usina e cenários meteorológicos amostrados, com incerteza crescente.

### 2.4 Escopo hierárquico do cálculo

O modelo usará três níveis, cada um com função diferente:

1. **Usina selecionada:** concentra a resposta final. Probabilidade, geração potencial, capacidade operacional, MWh restringidos, recorrência e previsão pertencerão somente à usina selecionada.
2. **Usinas do mesmo conjunto:** serão usadas para reconciliar a energia pública do conjunto e estimar qual parcela pertence à usina selecionada. A soma das parcelas individuais deverá conservar o total do conjunto.
3. **Todas as usinas ligadas ao ponto:** terão geração, disponibilidade, capacidade operacional, meteorologia e estado de manutenção simulados. Esses dados serão usados para estimar a pressão sistêmica e o envelope de geração aceita do ponto, incluindo outras tecnologias quando os dados as mostrarem. Os totais dos conjuntos serão derivados das usinas correspondentes para evitar dupla contagem.

```text
available_generation_j_t = potential_generation_j_t * availability_j_t * maintenance_derate_j_t
generation_potential_point_t = sum(available_generation_j_t for j in point)
point_excess_t = max(0, generation_potential_point_t - accepted_point_envelope_t)
```

`maintenance_derate_j_t` será igual a 1 sem manutenção e diminuirá conforme a indisponibilidade agendada da usina. A demonstração manterá agendas simuladas para as usinas participantes do ponto, como se várias usinas utilizassem o produto. Para cada previsão serão calculados dois cenários determinísticos sobre as mesmas amostras meteorológicas: cenário sem as manutenções agendadas e cenário com as manutenções agendadas. A diferença produzirá `network_relief_mw`, `avoided_curtailment_mwh` e `risk_reduction_percentage_points`.

A futura janela candidata da usina selecionada será aplicada como um terceiro contrafactual. O modelo estimará quanto a retirada dessa usina durante 72 horas altera a pressão do ponto e o curtailment das demais usinas. Nesta etapa, as agendas serão consumidas somente pelo cálculo da Exposição. Não haverá integração com a aba Manutenção.

O excesso do ponto será uma feature para o risco da usina selecionada. A energia das demais entidades nunca será apresentada como energia da usina selecionada.

### 2.5 Procedência interna

Os rótulos internos serão:

- `ONS_PUBLICO`: identificadores, vínculos, capacidade cadastrada, indicador histórico de restrição e observações públicas;
- `PROXY_CALCULADO`: energia histórica individual reconciliada, distribuições e métricas derivadas;
- `SIMULADO`: estado atual, geração potencial futura, limite operacional estimado, probabilidade e energia futura;
- `CLIENTE_INFORMADO`: reservado para dados fornecidos futuramente pelo cliente.

`SIMULADO_FROM_ONS_HISTORY` poderá aparecer somente no campo interno `simulation_method`. O campo `origin` continuará sendo `SIMULADO`.

A interface não exibirá os rótulos de procedência, o método de rateio, o método de ingestão, a versão de schema, hashes ou distinções técnicas entre valor público, calculado e simulado. Esses metadados permanecerão no backend para consistência, validação e auditoria interna.

## 3. Contrato previsto para a tela Exposição

O contrato consolidado continuará sendo servido por:

```text
GET /v1/exposure/assets
GET /v1/assets/{asset_id}/exposure-view
```

A resposta por usina incluirá:

```json
{
  "asset": {
    "asset_id": "RNEM01",
    "entity_level": "plant",
    "ons_group_id": "CJU_RNRDV",
    "ons_group_name": "Rio do Vento"
  },
  "simulated_telemetry": {
    "generation_mw": 0.0,
    "potential_generation_mw": 0.0,
    "availability_mw": 0.0,
    "operational_capacity_mw": 0.0,
    "accepted_generation_limit_mw": 0.0,
    "weather_value": 0.0,
    "weather_unit": "m/s"
  },
  "observed_impact": {
    "total_curtailed_energy": {"value": 0.0, "unit": "MWh"},
    "curtailed_day_share": {"value": 0.0, "unit": "%"},
    "allocation_coverage": {"value": 0.0, "unit": "%"}
  },
  "point_context": {
    "potential_generation_mw": 0.0,
    "accepted_generation_envelope_mw": 0.0,
    "estimated_excess_mw": 0.0,
    "scheduled_maintenance_relief_mw": 0.0,
    "entity_count": 0,
    "simulated_entities": []
  },
  "forecast_60d": {
    "points": [
      {
        "forecast_date": "YYYY-MM-DD",
        "display_label": "DD/MM",
        "expected_curtailed_mwh": 0.0,
        "lower_mwh": 0.0,
        "upper_mwh": 0.0,
        "curtailment_probability": 0.0,
        "potential_generation_mwh": 0.0,
        "accepted_generation_envelope_mwh": 0.0,
        "scheduled_maintenance_relief_mwh": 0.0,
        "avoided_curtailment_mwh": 0.0,
        "risk_reduction_percentage_points": 0.0
      }
    ],
    "critical_windows_72h": [
      {
        "rank": 1,
        "starts_at": "YYYY-MM-DDTHH:MM:SSZ",
        "ends_at": "YYYY-MM-DDTHH:MM:SSZ",
        "expected_curtailed_mwh": 0.0,
        "curtailment_probability": 0.0,
        "scheduled_maintenance_relief_mwh": 0.0,
        "avoided_curtailment_mwh": 0.0,
        "candidate_maintenance_relief_mwh": 0.0
      }
    ],
    "probability_status": "backtested_empirical",
    "simulation_method": "SIMULADO_FROM_ONS_HISTORY"
  },
  "narrative": {
    "secao-ativo": {"paragraphs": [], "generation_mode": "bedrock"},
    "secao-resumo": {"paragraphs": [], "generation_mode": "bedrock"},
    "secao-previsao": {"paragraphs": [], "generation_mode": "bedrock"},
    "secao-razao-origem": {"paragraphs": [], "generation_mode": "bedrock"},
    "secao-recorrencia": {"paragraphs": [], "generation_mode": "bedrock"},
    "secao-qualidade": {"paragraphs": [], "generation_mode": "bedrock"}
  }
}
```

O modo de geração poderá ser `bedrock`, `cached_bedrock` ou `deterministic_fallback`, mas essa distinção ficará no contrato interno. A interface usará o título constante “Análise dos dados” em todas as seções e não identificará se o texto veio do Bedrock, do cache ou do fallback. Falhas técnicas nunca aparecerão ao usuário.

### 3.1 Regras do forecast diário e das janelas de 72 horas

O backend entregará exatamente 60 pontos diários ordenados e sem lacunas. Cada ponto terá data ISO, label `DD/MM`, MWh esperados, limites inferior e superior e probabilidade diária de curtailment entre 0 e 100% para a usina selecionada.

A interface substituirá o gráfico de barras por um gráfico em linha. Todos os 60 dias terão marcador e label de data. O tooltip de cada marcador mostrará pelo menos data completa, energia restringida esperada em MWh e risco de curtailment em %. A faixa de incerteza poderá aparecer como área sombreada em torno da linha. Em telas estreitas, o gráfico permitirá rolagem horizontal para preservar os 60 labels sem omiti-los.

As janelas não serão agrupamentos semanais. O motor trabalhará com a série subdiária de 30 minutos e avaliará todas as janelas móveis de exatamente 72 horas, equivalentes a 144 intervalos consecutivos. Para cada cenário simulado `s` e janela `w`:

```text
curtailed_mwh_s_w = sum(curtailed_mw_s_t * 0.5 for t in w)
window_expected_mwh_w = mean(curtailed_mwh_s_w for s in scenarios)
window_probability_w = mean(curtailed_mwh_s_w > 0 for s in scenarios)
```

As três janelas críticas serão ordenadas primeiro por `window_expected_mwh`, depois por `window_probability`. Depois de selecionar uma janela, todas as candidatas que se sobreponham a ela serão removidas. Assim, a interface mostrará três períodos distintos, e não três deslocamentos do mesmo evento. Cada janela exibirá início, fim, MWh esperados, risco em %, alívio das manutenções já agendadas e alívio adicional do contrafactual de manutenção da usina selecionada.

## 4. Conteúdo da análise por Inteligência Artificial

Cada seção receberá somente seu subconjunto de evidências:

1. `secao-ativo`: nome da usina, tecnologia, capacidade cadastrada, conjunto, ponto, estado e telemetria operacional simulada.
2. `secao-resumo`: energia individual estimada, frequência histórica de dias restritos, médias recentes, capacidade operacional estimada e cobertura do rateio.
3. `secao-previsao`: energia esperada, faixa de incerteza, probabilidade de restrição, previsão meteorológica, geração potencial da usina, pressão agregada do ponto, limite operacional estimado e três janelas críticas de 72 horas.
4. `secao-razao-origem`: razões publicadas no conjunto, telemetria simulada das entidades do ponto e impacto das manutenções agendadas. O texto não atribuirá uma razão do conjunto à usina como causa individual comprovada.
5. `secao-recorrencia`: dias da semana, horários, sazonalidade histórica da própria usina e relação observada com vento ou irradiância.
6. `secao-qualidade`: cobertura, defasagem, dados ausentes, cobertura de alocação, horizonte meteorológico e incerteza da simulação.

O Bedrock não poderá criar números, alterar unidades, inferir causa, declarar aprovação do ONS, afirmar telemetria privada, prometer ocorrência futura ou recomendar manutenção e bateria. O texto apresentado também não poderá expor rótulos de procedência, método de simulação, rateio ou origem técnica dos campos.

## 5. Plano de implementação

### Tarefa 1: Congelar a linha de base e validar a coorte de usinas

**Objetivo:** provar quais usinas individuais pertencem aos cinco contextos atuais antes de alterar contratos.

**Arquivos:**

- Criar: `backend/tools/build_individual_plant_cohort.py`
- Criar: `backend/tests/test_individual_plant_cohort.py`
- Criar: `backend/src/curtailess/data/individual_plant_catalog.json`
- Ler somente: artefatos ONS detalhados e cadastrais fornecidos por argumento ao script

**Passos:**

1. Escrever testes que rejeitem `asset_id` iniciado por `CJU_`.
2. Escrever testes que exijam `id_ons`, nome, CEG quando disponível, grupo, ponto, tecnologia, estado, capacidade e vigência.
3. Implementar o extrator com entradas explícitas para `restricao_coff_eolica_detail_tm`, `restricao_coff_fotovoltaica_detail_tm`, `usina_conjunto` e `capacidade-geracao`.
4. Gerar um relatório de IDs ausentes, vínculos ambíguos, duplicatas e cobertura histórica de cada candidata.
5. Classificar as candidatas de cada contexto por vínculo inequívoco, cobertura histórica, meteorologia e capacidade cadastrada.
6. Materializar exatamente uma usina por contexto e exatamente cinco usinas no catálogo final.
7. Verificar que cada registro selecionável representa uma usina individual e que nenhum conjunto aparece como opção.

**Comandos de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_individual_plant_cohort.py
/home/carloshnp/.hermes/bin/uv run python tools/build_individual_plant_cohort.py --help
```

**Commit previsto:** `feat(exposure): materialize individual plant cohort`

### Tarefa 2: Implementar o histórico individual e a reconciliação com o conjunto

**Objetivo:** produzir séries históricas diárias por usina sem apresentar o rateio como medição direta.

**Arquivos:**

- Criar: `backend/src/curtailess/plant_exposure_history.py`
- Criar: `backend/tests/test_plant_exposure_history.py`
- Criar: `backend/src/curtailess/data/individual_plant_history.json`
- Modificar: `backend/src/curtailess/provenance.py`, somente se os construtores atuais não cobrirem os novos campos

**Passos:**

1. Escrever um teste de ocorrência baseado em `flg_geracaorestrita`.
2. Escrever um teste de exclusão de intervalos inválidos e duplicados.
3. Escrever um teste que treine a curva de geração somente com intervalos sem restrição.
4. Escrever um teste para pesos baseados na perda potencial individual.
5. Escrever um teste para fallback de capacidade somente entre usinas marcadas como restritas.
6. Escrever um teste de conservação:

```python
assert abs(sum(plant_mwh) - group_public_mwh) <= 1e-6
```

7. Implementar agregação de 30 minutos para dia.
8. Montar a série histórica de todas as usinas do conjunto para reconciliar o total publicado.
9. Montar a série agregada de todas as usinas ligadas ao ponto para formar o contexto sistêmico, derivando os totais dos conjuntos sem somá-los novamente.
10. Registrar `allocation_method`, `allocation_coverage_pct`, `origin` e limitações em cada agregado interno.
11. Falhar quando o total do conjunto não puder ser reconciliado, sem distribuir silenciosamente a diferença.
12. Garantir que somente os resultados da usina selecionada sejam apresentados como métricas individuais.

**Comando de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_plant_exposure_history.py
```

**Commit previsto:** `feat(exposure): derive plant-level historical exposure`

### Tarefa 3: Implementar o modelo de risco e severidade por usina

**Objetivo:** prever separadamente a probabilidade de restrição e os MWh potencialmente restringidos.

**Arquivos:**

- Criar: `backend/src/curtailess/plant_exposure_forecast.py`
- Criar: `backend/src/curtailess/point_exposure_simulation.py`
- Criar: `backend/tests/test_plant_exposure_forecast.py`
- Criar: `backend/tests/test_point_exposure_simulation.py`
- Criar: `backend/src/curtailess/data/individual_plant_forecast.json`
- Criar: `backend/src/curtailess/data/simulated_point_maintenance_schedule.json`
- Modificar: `backend/src/curtailess/materialize_exposure_forecast.py`
- Substituir gradualmente: `backend/src/curtailess/data/five_asset_forecast.json`
- Substituir gradualmente: `backend/src/curtailess/data/five_asset_history_summary.json`

**Modelo de probabilidade:**

- alvo binário por usina e dia baseado no indicador detalhado;
- validação temporal com corte cronológico, sem embaralhamento;
- taxas históricas da própria usina por mês, dia da semana e hora;
- médias recentes de 7 e 30 dias calculadas com `shift(1)`;
- telemetria simulada da usina, incluindo capacidade operacional, geração potencial e disponibilidade;
- vento em alturas compatíveis para eólica ou irradiância e temperatura para solar;
- geração potencial agregada das demais usinas ligadas ao mesmo ponto, com totais de conjunto derivados sem dupla contagem;
- excesso estimado no ponto, calculado antes da previsão da usina;
- estado do conjunto usado como contexto disponível antes da previsão;
- suavização hierárquica para usinas com poucos eventos;
- calibração aceita somente quando melhorar o Brier em caminhos temporais independentes;
- caso contrário, `probability_status = empirical_uncalibrated` e resultado negativo documentado.

**Modelo de energia:**

- geração potencial estimada pela curva da própria usina e pela meteorologia prevista;
- capacidade operacional disponível estimada pela telemetria simulada da usina;
- envelope de geração aceita estimado com a pressão agregada de todas as entidades do ponto;
- MWh restringidos calculados pelo excedente entre potencial da usina e envelope aceito para a usina;
- intervalos de incerteza obtidos de resíduos fora da amostra e ensembles meteorológicos;
- previsão meteorológica direta no horizonte útil de até aproximadamente 16 dias;
- climatologia, sazonalidade e cenários amostrados para completar 60 dias;
- nenhum dado real do intervalo previsto poderá entrar como feature.

**Simulação do ponto e manutenção:**

- gerar telemetria simulada em intervalos de 30 minutos para todas as usinas ligadas ao ponto, mesmo quando apenas uma das cinco usinas estiver selecionada;
- preservar correlação meteorológica espacial entre usinas próximas, evitando amostras independentes incompatíveis;
- aplicar as indisponibilidades da agenda simulada das usinas participantes;
- calcular a pressão do ponto sem manutenção, com manutenções agendadas e com a janela candidata da usina selecionada;
- calcular alívio da rede em MW, MWh de curtailment evitados e redução do risco em pontos percentuais;
- agregar cada dia para o gráfico de 60 pontos sem descartar a série subdiária;
- avaliar todas as janelas móveis de 144 intervalos e selecionar as três janelas de 72 horas críticas e não sobrepostas;
- manter essa agenda isolada da aba Manutenção nesta etapa.

**Testes obrigatórios:**

1. nenhuma feature usa `val_geracaoverificada`, disponibilidade ou fator de capacidade do intervalo previsto;
2. lags usam `shift(1)`;
3. previsões respeitam capacidade instalada e não produzem valores negativos;
4. `0 <= probability <= 1`;
5. `lower <= expected <= upper`;
6. a energia prevista não é obtida por `probability * severity`;
7. o backtest publica Brier, erro absoluto médio, cobertura do intervalo e baselines;
8. uma regressão específica impede o retorno da antiga probabilidade de aproximadamente 99% sem evidência fora da amostra;
9. previsões meteorológicas respeitam `issued_at` e não vazam observações futuras;
10. o ponto agrega e simula todas as entidades vinculadas, mas a saída individual contém somente a parcela da usina selecionada;
11. o catálogo final contém exatamente cinco previsões de usinas individuais;
12. a indisponibilidade agendada reduz a geração disponível da usina participante nos intervalos corretos;
13. cenários com e sem manutenção reutilizam as mesmas amostras meteorológicas;
14. o alívio calculado é a diferença entre os cenários e não pode ser negativo sem diagnóstico explícito;
15. cada ponto diário tem data, label, MWh e probabilidade;
16. existem exatamente três janelas de 72 horas, cada uma com 144 intervalos e sem sobreposição;
17. nenhuma janela semanal é produzida.

**Comando de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_plant_exposure_forecast.py tests/test_point_exposure_simulation.py tests/test_exposure_forecast_import.py
```

**Commit previsto:** `feat(exposure): forecast plant curtailment risk and energy`

### Tarefa 4: Migrar os contratos da API de conjunto para usina

**Objetivo:** tornar a usina individual a entidade principal sem esconder os vínculos sistêmicos.

**Arquivos:**

- Modificar: `backend/src/curtailess/schemas.py`
- Modificar: `backend/src/curtailess/exposure_view.py`
- Modificar: `backend/src/curtailess/exposure_forecast_import.py`
- Modificar: `backend/tests/test_exposure_view.py`
- Modificar: `backend/tests/test_exposure_forecast_import.py`

**Passos:**

1. Alterar `entity_level` para o literal `plant`.
2. Adicionar `ons_group_id`, `ons_group_name`, `ceg` e `allocation_coverage`.
3. Fixar o catálogo da demonstração em exatamente cinco usinas verificadas.
4. Remover `APPROVED_ASSET_IDS` baseado em conjuntos e carregar os cinco IDs individuais do catálogo empacotado.
5. Fazer `build_exposure_view()` rejeitar conjuntos e ativos desconhecidos.
6. Trocar textos determinísticos de conjunto por usina.
7. Incluir `simulated_telemetry` com capacidade operacional e condições meteorológicas da usina.
8. Incluir `point_context` calculado com telemetria simulada de todas as entidades ligadas ao ponto.
9. Incluir agendas simuladas, alívio da rede e curtailment evitado nos cenários com manutenção.
10. Manter conjunto e ponto de conexão como contexto, sem atribuir suas energias à usina.
11. Incluir 60 pontos diários com label, probabilidade, MWh e impacto das manutenções.
12. Incluir exatamente três janelas críticas não sobrepostas de 72 horas.
13. Incluir a procedência de cada bloco no `input_digest`, sem expor os rótulos na interface.

**Comando de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_exposure_view.py tests/test_exposure_forecast_import.py
```

**Commit previsto:** `refactor(exposure): make plant the primary entity`

### Tarefa 5: Gerar e validar uma narrativa de IA por seção

**Objetivo:** usar o Bedrock para interpretar cada seção sem permitir que o modelo altere os fatos.

**Arquivos:**

- Modificar: `backend/src/curtailess/exposure_narrative.py`
- Modificar: `backend/src/curtailess/schemas.py`
- Modificar: `backend/tests/test_exposure_narrative.py`

**Passos:**

1. Alterar `ExposureNarrative` para seis objetos de seção com `paragraphs` e `generation_mode`.
2. Criar `_section_evidence_payloads(view)` para limitar os fatos entregues a cada seção.
3. Manter uma única chamada `bedrock-runtime.converse()` para as seis seções, com `maxTokens` explícito e retry adaptativo.
4. Validar cada seção somente contra seus próprios números permitidos.
5. Rejeitar números, unidades, nomes ou relações que não existam no bloco correspondente.
6. Rejeitar afirmações de causa, aprovação do ONS, telemetria privada, capacidade física confirmada, certeza futura e recomendações fora da Exposição.
7. Adicionar proibições específicas contra tratar a razão do conjunto como causa comprovada da usina.
8. Rejeitar narrativas que exponham `ONS_PUBLICO`, `PROXY_CALCULADO`, `SIMULADO`, `simulation_method`, método de rateio ou origem técnica.
9. Produzir fallback determinístico separado por seção sem esses rótulos.
10. Testar saída JSON parcial, chave ausente, texto excessivo, número inventado, procedência exposta e conteúdo proibido.
11. Verificar que a chamada continua sem `temperature` e com `maxTokens` explícito.

**Comando de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_exposure_narrative.py
```

**Commit previsto:** `feat(exposure): validate AI analysis per section`

### Tarefa 6: Versionar narrativas e aplicar fallback por seção

**Objetivo:** preservar a última narrativa válida compatível quando o Bedrock falhar.

**Arquivos:**

- Modificar: `backend/src/curtailess/exposure_narrative_repository.py`
- Modificar: `backend/src/curtailess/materialize_exposure_narratives.py`
- Modificar: `backend/src/curtailess/main.py`
- Modificar: `backend/tests/test_exposure_narrative_repository.py`
- Criar ou modificar: teste de rota da Exposição em `backend/tests/test_exposure_view.py`

**Passos:**

1. Atualizar a versão do schema da narrativa.
2. Persistir digest por seção, além do digest consolidado.
3. Ler primeiro a versão exata dos dados da seção.
4. Aceitar a versão `CURRENT` somente quando a validação contra a evidência atual passar.
5. Aplicar fallback por seção, sem descartar cinco seções válidas por causa de uma seção inválida.
6. Usar narrativa determinística quando não houver narrativa Bedrock compatível.
7. Não retornar erro técnico do Bedrock na API da tela.
8. Testar mistura segura de `bedrock`, `cached_bedrock` e `deterministic_fallback`.

**Comando de verificação:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run pytest -q tests/test_exposure_narrative_repository.py tests/test_exposure_view.py
```

**Commit previsto:** `feat(exposure): preserve compatible section narratives`

### Tarefa 7: Migrar o cliente TypeScript para usinas individuais

**Objetivo:** validar integralmente o novo contrato antes de renderizar os dados.

**Arquivos:**

- Modificar: `frontend/app/domain/types.ts`
- Modificar: `frontend/app/domain/exposure-api.ts`
- Modificar: `frontend/app/domain/exposure-api.test.ts`
- Modificar: `frontend/app/state/exposure-context.tsx`
- Modificar: `frontend/app/state/exposure-context.test.tsx`

**Passos:**

1. Alterar `entityLevel` para `plant`.
2. Adicionar grupo, CEG, cobertura de alocação, geração potencial, envelope aceito, telemetria do ponto, impacto de manutenção e metadados da narrativa.
3. Fazer o Zod rejeitar `generation_group` no catálogo da Exposição.
4. Validar exatamente 60 pontos diários consecutivos quando o forecast estiver disponível.
5. Exigir data, label, MWh, probabilidade e tooltip completo em cada ponto.
6. Validar exatamente três janelas de 72 horas sem sobreposição.
7. Validar probabilidade, intervalo de energia e relações entre potencial, envelope, manutenção e energia restringida.
8. Manter o seletor da Exposição isolado do `AnalysisProvider` usado nas outras telas.
9. Não integrar esse cenário à aba Manutenção nesta etapa.
10. Atualizar fixtures para uma usina real verificada e as entidades simuladas do ponto.

**Comando de verificação:**

```bash
cd frontend
npm test -- --run app/domain/exposure-api.test.ts app/state/exposure-context.test.tsx
```

**Commit previsto:** `refactor(exposure): consume plant-level API contract`

### Tarefa 8: Corrigir seletor, topologia e linguagem da usina

**Objetivo:** permitir que o usuário selecione uma usina e entenda seu conjunto e ponto de conexão.

**Arquivos:**

- Modificar: `frontend/app/components/layout/asset-picker.tsx`
- Modificar: `frontend/app/components/topology/asset-topology.tsx`
- Modificar: `frontend/app/components/illustrations/wind-network-illustration.tsx`
- Modificar: `frontend/app/components/illustrations/solar-network-illustration.tsx`
- Modificar: `frontend/app/components/illustrations/energy-network-illustration.tsx`, se necessário

**Passos:**

1. Trocar o título para “Usina em análise”.
2. Exibir exatamente cinco opções de usinas individuais.
3. Exibir nome, tecnologia, estado e conjunto no detalhe de cada opção.
4. Proibir opções cujo ID seja `CJU_*`.
5. Representar a sequência `usina → conjunto ONS → ponto de conexão` na topologia.
6. Representar as demais usinas do conjunto no contexto de reconciliação.
7. Representar todas as usinas do ponto no contexto de pressão sistêmica e derivar os agrupamentos sem dupla contagem.
8. Manter lista legível no celular e o alvo mínimo de 44 px.
9. Remover frases que afirmem que a entidade selecionada é um conjunto.
10. Não exibir rótulos de procedência nem identificar dados públicos, calculados ou simulados.

**Comando de verificação:**

```bash
cd frontend
npm run typecheck
npm test -- --run
```

**Commit previsto:** `fix(exposure): select and contextualize individual plants`

### Tarefa 9: Atualizar as seis seções da Exposição

**Objetivo:** apresentar métricas e narrativas coerentes com a usina individual.

**Arquivos:**

- Modificar: `frontend/app/features/exposure/exposure-screen.tsx`
- Modificar: `frontend/app/components/charts/exposure-charts.tsx`
- Modificar: `frontend/app/components/layout/analysis-section.tsx`

**Mudanças por seção:**

1. **Ativo:** usina, capacidade cadastrada, capacidade operacional estimada, conjunto, ponto, tecnologia, estado e telemetria operacional disponível.
2. **Resumo:** MWh históricos estimados da usina, participação de dias com restrição, médias de 7 e 30 dias, geração atual e capacidade operacional.
3. **Previsão:** substituir barras por uma linha de MWh/dia com faixa de incerteza e marcador em todos os 60 dias. Todos os dias terão label `DD/MM`. O tooltip mostrará data completa, MWh previstos e risco de curtailment em %. A seção também apresentará as três janelas críticas não sobrepostas de 72 horas, nunca semanas.
4. **Razão e origem:** comportamento do conjunto, telemetria de todas as entidades do ponto e comparação com e sem manutenções já agendadas, sem apresentar a energia das demais entidades como energia da usina selecionada.
5. **Recorrência:** distribuição por dia e hora da própria usina e relação histórica com vento ou irradiância.
6. **Qualidade:** cobertura da série individual, defasagem, ausências, duplicatas, cobertura do rateio e incerteza crescente após o horizonte meteorológico útil.

Cada coluna de análise usará o mesmo título visível:

```text
Análise dos dados
```

A interface não distinguirá Bedrock, cache e fallback. A interface também não exibirá procedência, método de simulação, modelo, prompt, hash, bucket, versão interna do schema ou erro técnico.

**Comando de verificação:**

```bash
cd frontend
npm run typecheck
npm run lint
npm test -- --run
```

**Commit previsto:** `feat(exposure): present plant risk and AI interpretation`

### Tarefa 10: Atualizar testes de integração e End-to-End

**Objetivo:** provar que a tela inteira trabalha com usinas sem afetar as outras rotas.

**Arquivos:**

- Modificar: `frontend/tests/e2e/main-flow.spec.ts`
- Modificar: fixtures de rede usadas pelo Playwright, se existirem
- Modificar: `backend/tests/test_exposure_view.py`

**Cenários obrigatórios:**

1. o catálogo da Exposição contém exatamente cinco usinas individuais e nenhum ID `CJU_*`;
2. a troca de seleção altera para outra usina individual;
3. a tela informa o conjunto e o ponto como contexto;
4. o gráfico usa linha, não barras, e seus 60 pontos de MWh e probabilidade pertencem à mesma usina;
5. todos os 60 dias têm label, marcador e tooltip com data, MWh e risco em %;
6. a pressão do ponto considera telemetria simulada de todas as entidades ligadas ao ponto;
7. manutenções simuladas de outras usinas reduzem a geração disponível nos intervalos agendados e atualizam o panorama;
8. a energia das demais entidades não é atribuída à usina selecionada;
9. aparecem exatamente três janelas críticas, distintas e não sobrepostas de 72 horas;
10. nenhuma janela semanal aparece;
11. as seis seções apresentam narrativa não vazia com o título constante “Análise dos dados”;
12. Bedrock, cache e fallback não recebem rótulos diferentes na interface;
13. uma falha de narrativa não derruba métricas e gráficos;
14. a interface não mostra procedência, método de simulação ou origem técnica;
15. a troca feita em `/exposicao` não altera Manutenção ou Bateria;
16. o gráfico móvel preserva os 60 labels por rolagem horizontal controlada sem criar overflow na página;
17. a topologia móvel mostra usina, conjunto e ponto;
18. os controles permanecem acessíveis por teclado.

**Comando de verificação:**

```bash
cd frontend
npm run test:e2e
```

**Commit previsto:** `test(exposure): cover individual plant experience`

### Tarefa 11: Atualizar documentação de auditoria

**Objetivo:** registrar o novo método e corrigir a documentação que hoje encerra a análise no conjunto.

**Arquivos:**

- Criar: `docs/audits/2026-09-27-granularidade-por-usina-e-narrativas-ia.md`
- Modificar: `docs/audits/2026-09-27-probabilidade-e-granularidade-ons.md`
- Modificar: `docs/superpowers/specs/2026-09-27-exposure-frontend-bedrock-design.md`
- Modificar: `docs/plans/2026-09-27-exposure-frontend-bedrock-integration.md`

**Conteúdo obrigatório:**

- fontes individuais, agregadas e meteorológicas;
- critério de seleção das cinco usinas;
- definição do evento de restrição por usina;
- fórmula de energia individual;
- conservação do total do conjunto;
- uso de telemetria simulada de todas as entidades do ponto na pressão sistêmica;
- fallback de rateio;
- telemetria simulada e capacidade operacional estimada;
- cenários com e sem manutenções já agendadas;
- cálculo do alívio da rede e curtailment evitado;
- definição e ranking das janelas não sobrepostas de 72 horas;
- métricas de backtest por usina;
- resultado das cinco usinas e eventuais resultados negativos;
- transição da previsão meteorológica para cenários climatológicos;
- contrato dos 60 pontos diários e do gráfico em linha;
- limites do envelope operacional estimado;
- política de validação e fallback das narrativas.

**Commit previsto:** `docs(exposure): document plant simulation and AI narratives`

### Tarefa 12: Executar a verificação completa local

**Objetivo:** confirmar que backend, frontend e template permanecem válidos antes de pedir autorização para deploy.

**Backend:**

```bash
cd backend
/home/carloshnp/.hermes/bin/uv run ruff check .
/home/carloshnp/.hermes/bin/uv run ruff format --check .
/home/carloshnp/.hermes/bin/uv run pytest -q
```

**Frontend:**

```bash
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
npm run test:e2e
```

**Raiz:**

```bash
git diff --check
sam validate --lint
sam build
```

**Verificação manual local:**

1. iniciar FastAPI em `127.0.0.1:8000`;
2. iniciar Vite em uma porta livre e confirmar a URL informada pelo próprio Vite;
3. abrir `/exposicao`;
4. confirmar que o seletor contém exatamente cinco usinas, incluindo eólica e solar;
5. confirmar usina, conjunto, ponto, telemetria, meteorologia, MWh, probabilidade e seis narrativas;
6. confirmar que o contexto do ponto simula todas as entidades vinculadas sem atribuir suas energias à usina;
7. confirmar que uma manutenção agendada simulada reduz a geração do ponto e recalcula MWh e risco;
8. confirmar gráfico em linha, 60 labels diários e tooltip com data, MWh e risco em %;
9. confirmar três janelas críticas não sobrepostas de exatamente 72 horas e ausência de janelas semanais;
10. confirmar ausência de `CJU_*` nas opções selecionáveis;
11. confirmar ausência de rótulos de procedência, simulação ou origem técnica no frontend;
12. confirmar ausência de erros no console;
13. encerrar os dois processos e verificar que as portas ficaram livres.

Nenhum `sam deploy` fará parte desta tarefa.

## 6. Critérios de aceitação

A implementação poderá ser considerada pronta para teste do usuário quando:

- o seletor da Exposição contiver exatamente cinco usinas individuais verificadas, uma por contexto atual;
- cada usina apresentar seu conjunto e ponto de conexão;
- nenhum ID `CJU_*` for usado como `asset_id` selecionável;
- a telemetria simulada da usina alimentar todas as seis seções e o forecast;
- a capacidade operacional disponível da usina for estimada pela simulação;
- a ocorrência histórica vier do indicador detalhado da própria usina;
- os MWh individuais forem reconciliados internamente com o conjunto;
- todas as usinas do ponto tiverem telemetria simulada e participarem da estimativa de pressão sistêmica, com totais de conjunto derivados sem dupla contagem;
- agendas simuladas de manutenção das usinas participantes alterarem a geração disponível nos intervalos corretos;
- o modelo comparar cenário sem manutenção, cenário com manutenções agendadas e contrafactual da janela candidata;
- o resultado calcular alívio da rede, MWh evitados e redução do risco;
- nenhuma energia das outras entidades for apresentada como energia da usina selecionada;
- previsões meteorológicas entrarem no horizonte útil e cenários climatológicos completarem os 60 dias;
- o forecast apresentar exatamente 60 dias consecutivos com label, MWh, faixa de incerteza e risco em %;
- o frontend usar gráfico em linha, marcadores diários e tooltip completo, sem barras;
- o forecast apresentar exatamente três janelas críticas não sobrepostas de 72 horas, sem agrupamento semanal;
- o forecast apresentar geração potencial e limite operacional estimado;
- o backtest temporal por usina publicar resultados e baselines;
- cada uma das seis seções receber uma interpretação validada;
- o frontend não mostrar rótulos de procedência, simulação ou origem técnica;
- Bedrock, cache e fallback usarem o mesmo título “Análise dos dados” no frontend;
- números e decisões continuarem determinísticos;
- uma falha Bedrock não remover dados nem aparecer como erro técnico ao cliente;
- todas as verificações locais passarem;
- nenhum recurso AWS for criado ou alterado.

## 7. Riscos e controles

### Vínculo ambíguo entre usina e conjunto

O vínculo pode mudar por vigência ou apresentar identificadores incompletos. A materialização usará a data de validade e falhará em ambiguidades, sem escolher o primeiro resultado.

### Rateio individual fraco

Alguns intervalos podem não sustentar uma diferença confiável entre potencial e geração aceita. A resposta publicará a cobertura de alocação. O frontend mostrará “Indisponível” quando a cobertura mínima não for alcançada.

### Probabilidade superconfiante

O modelo anterior aproximou 99% por definição inadequada e calibração fraca. O novo modelo usará alvo individual explícito, teste temporal e calibração somente quando melhorar o Brier em trajetórias independentes. Resultados ruins permanecerão visíveis na auditoria.

### Horizonte de 60 dias

Previsões meteorológicas perdem resolução no horizonte longo. O contrato distinguirá a parte apoiada por previsão meteorológica da parte baseada em climatologia histórica. A narrativa não tratará datas distantes como certeza operacional.

### Manutenções das demais usinas

As agendas das usinas participantes serão simuladas nesta etapa. Os cenários com e sem manutenção usarão as mesmas amostras meteorológicas para que a diferença represente somente a indisponibilidade planejada. O produto apresentará redução ou mitigação como resultado do cenário, não como coordenação real entre agentes nem como compromisso operacional das usinas.

### Texto Bedrock incompatível

A validação por seção rejeitará números e afirmações sem suporte. O sistema usará narrativa Bedrock armazenada compatível ou fallback determinístico, sem alterar as métricas.

## 8. Decisão solicitada ao usuário

A aprovação deste plano autoriza, em uma etapa posterior, a implementação local das doze tarefas e somente dos arquivos listados ou de arquivos de teste diretamente necessários. Deploy, chamadas reais ao Bedrock, escrita em DynamoDB e importação para AWS continuarão exigindo autorização separada.
