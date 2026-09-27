# Public ONS Data and AI Maintenance Windows Implementation Plan

> **For Hermes:** Use subagent-driven-development to implement this plan task by task, with no more than three concurrent subagents.

**Goal:** Replace the fixed maintenance demo with an auditable decision flow that ingests public ONS data, estimates a simulated current plant state, ranks eligible multi-day maintenance windows, returns a final backend-selected decision with a Bedrock explanation, and deploys locally to the hackathon AWS account.

**Architecture:** Public ONS Parquet files are copied into immutable S3 keys through an idempotent ingestion ledger. Dataset-specific materializers preserve compact current and historical facts in DynamoDB and larger facts in S3. A deterministic plant-state estimator combines current public ONS inputs with public historical SCADA-derived distributions. A deterministic maintenance engine filters and ranks candidate windows. Bedrock receives only the selected slot, reason codes, fact references, and limitations, and cannot alter numeric facts or eligibility. The delivered decision is stored idempotently and rendered before its explanation.

**Tech stack:** Python 3.12, FastAPI, Pydantic v2, DuckDB, boto3, AWS SAM, Lambda, S3, SQS, DynamoDB, EventBridge Scheduler, Amazon Bedrock Converse API, React Router, TypeScript, Vitest, Playwright.

**Approved source specification:** `DADOS-PUBLICOS-E-DECISAO-DE-JANELAS-COM-IA-v1.md` in the hackathon strategy workspace.

**Deployment constraint:** Deploy locally with AWS profile `curtailess-hackathon` in `us-west-2`. The hackathon account cannot create a GitHub OIDC provider. GitHub Actions remains CI-only.

**Unavailable input:** Private continuous plant SCADA. Any current plant value inferred from public history must be labeled `SIMULADO`; public values and deterministic derivatives retain their own origin labels.

---

## Baseline captured on 2026-09-26

- Repository head before implementation: `76010b5a7b026945942b3b795357bef1d468dc35` on `develop`.
- Working branch: `feat/public-data-ai-maintenance-windows`.
- Backend: 40 tests passed and 1 failed because `backend/tests/test_materialization.py` reads an untracked absolute fixture at `/tmp/curtailess-ons-2026-08.parquet`.
- Frontend: 21 tests passed and the production build completed.
- AWS stack `curtailess-dev`: `UPDATE_COMPLETE`.
- Live Bedrock path: HTTP 200 using `us.anthropic.claude-opus-5`.
- Current data: 153 wind assets, no solar assets, and all exposed capacities are null.
- Current maintenance ranking: historical prototype with fixed behavior and no final decision record.

## Acceptance criteria

1. Every input and output field that affects a decision carries one of `ONS_PUBLICO`, `PROXY_CALCULADO`, `SIMULADO`, or `CLIENTE_INFORMADO`.
2. Public ONS history can be backfilled over bounded periods and rerun without duplicate processing.
3. Incremental discovery skips already materialized source fingerprints.
4. Wind and photovoltaic constrained-off datasets share one validated materializer.
5. Current public forecast/programming, historical generation, and identity/capacity data can feed the plant-state estimator when available.
6. Missing fresh public current data returns `REVIEW_REQUIRED`; the API never describes a historical sample as a current measurement.
7. The plant-state endpoint returns deterministic simulations for equal inputs and records the fallback level used.
8. The maintenance engine generates multi-day candidates, rejects ineligible windows with reason codes, and ranks eligible windows by the approved stable tuple.
9. The decision endpoint returns `SELECTED`, `NO_ELIGIBLE_WINDOW`, or `REVIEW_REQUIRED` and stores exact replayable output by `decision_id`.
10. Bedrock cannot change the backend-selected slot or introduce numeric facts. All Bedrock failures produce a deterministic explanation for the same decision.
11. The maintenance screen renders decision, explanation, evidence, limitations, and ranking in that order without requiring manual candidate selection.
12. The UI states that private SCADA and ONS approval are not evaluated.
13. Backend tests, Ruff, frontend tests, typecheck, lint, build, and current Playwright flows pass or any pre-existing stale E2E tests are updated with explicit evidence.
14. `sam validate`, `sam build`, and local `sam deploy --profile curtailess-hackathon` succeed.
15. Live API, decision replay, frontend, ingestion no-op replay, SQS, DLQ, and stack status are verified after deployment.

## Out of scope

- Private continuous SCADA ingestion.
- Claiming that a maintenance window is approved or safe according to the ONS.
- Writing interventions into ONS systems.
- AgentCore, Knowledge Bases, classic Bedrock Agents, or autonomous tool execution.
- Client CMMS integration and real work-order synchronization.
- Permanent GitHub deployment credentials.

---

### Task 1: Restore a portable green baseline

**Objective:** Remove the absolute test fixture dependency and establish reproducible backend and frontend checks.

**Files:**
- Modify: `backend/tests/test_materialization.py`
- Create: `backend/tests/fixtures/.gitkeep` only if generated fixtures cannot replace committed binaries
- Modify: `.github/workflows/ci.yml`
- Modify: `frontend/tests/e2e/main-flow.spec.ts` only for assertions proven stale against the current application

**Steps:**

1. Rewrite the materialization fixture to create a minimal Parquet file under pytest `tmp_path` with DuckDB.
2. Prove the existing test fails because of the absolute `/tmp` dependency.
3. Run the materialization test and full backend suite.
4. Run Ruff check and format check.
5. Run frontend unit tests, typecheck, lint, and build.
6. Run Playwright and classify each failure as stale test, missing API dependency, or product defect before editing it.

**Verification:**

```bash
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd ../frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

---

### Task 2: Add dataset and field-level provenance contracts

**Objective:** Create one strict vocabulary for dataset metadata and decision evidence.

**Files:**
- Create: `backend/src/curtailess/datasets.py`
- Modify: `backend/src/curtailess/schemas.py`
- Create: `backend/tests/test_datasets.py`
- Modify: `backend/tests/test_api.py`

**Contracts:**

```python
class DataOrigin(StrEnum):
    ONS_PUBLICO = "ONS_PUBLICO"
    PROXY_CALCULADO = "PROXY_CALCULADO"
    SIMULADO = "SIMULADO"
    CLIENTE_INFORMADO = "CLIENTE_INFORMADO"
```

`DatasetSpec` must define dataset ID, S3 prefix, technology, grain, period parser, required columns, aliases, source timezone, materializer, schema version, and enabled modes.

Initial registry:

- `restricao_coff_eolica_tm`
- `restricao_coff_fotovoltaica_tm`
- `programacao_x_previsao`
- `geracao_usina_2_ho`
- effective-dated asset/group/capacity identity sources actually verified in the ONS bucket

`EvidenceProvenance` must include origin, source URI or key, source SHA-256 when available, observed/effective timestamps, validity interval, method version, evidence ID, and limitations.

**Tests:**

- Exact enum values.
- Unknown dataset rejection.
- Dataset-specific period parsing.
- Every evidence object requires origin and method/source metadata.
- Public observations and simulated outputs cannot share the same evidence ID or origin.

---

### Task 3: Make ingestion idempotent and support bounded backfill

**Objective:** Enumerate historical and incremental source objects safely and suppress duplicate work.

**Files:**
- Modify: `backend/src/curtailess/ingestion.py`
- Create: `backend/src/curtailess/ingestion_state.py`
- Modify: `backend/tests/test_ingestion.py`
- Create: `backend/tests/test_ingestion_state.py`
- Modify: `template.yaml`
- Modify: `backend/tests/test_infrastructure_contract.py`

**Behavior:**

- Replace latest-only discovery with paginated object enumeration.
- Support `mode=backfill` with explicit dataset and inclusive period bounds.
- Support `mode=incremental` across enabled datasets.
- Parse periods through `DatasetSpec`, not filename slicing in the copy handler.
- Sort messages by dataset, period, and source key.
- Generate a source fingerprint from dataset, key, ETag, size, and last-modified timestamp.
- Claim work with a conditional DynamoDB update.
- Treat the same completed fingerprint as a no-op.
- Store raw bytes at a content-addressed key containing SHA-256.
- Verify existing content-addressed object metadata before reuse.
- Keep mutable processing status in the ledger and write final immutable manifests only after materialization.

**Ledger states:** `DISCOVERED`, `COPYING`, `COPIED`, `MATERIALIZING`, `MATERIALIZED`, `FAILED`.

**Tests:**

- Pagination and unordered objects.
- Multiple datasets and months.
- Backfill bounds and message cap.
- Malformed filenames.
- Duplicate discovery.
- Duplicate SQS delivery.
- Changed source at the same key.
- Expired processing lease.
- SHA mismatch.
- Failed retry followed by success.

---

### Task 4: Decouple copy and materialization with SQS

**Objective:** Ensure copied files are acknowledged separately from materialization success and failures remain recoverable.

**Files:**
- Modify: `backend/src/curtailess/ingestion.py`
- Refactor: `backend/src/curtailess/materialization.py`
- Modify: `template.yaml`
- Modify: `backend/tests/test_ingestion.py`
- Modify: `backend/tests/test_materialization.py`
- Modify: `backend/tests/test_infrastructure_contract.py`

**Infrastructure:**

- Add `IngestionLedgerTable`.
- Add `MaterializationQueue` and `MaterializationDeadLetterQueue`.
- Connect materialization Lambda through an SQS event source.
- Remove direct asynchronous Lambda invocation from `copy_handler`.
- Pass dataset, source period, source fingerprint, raw key, raw SHA-256, and manifest identity explicitly.
- Use partial batch failure reporting.

**Verification:**

- A failed materializer sends the record through SQS retry policy.
- Ledger reaches `MATERIALIZED` only after final curated writes succeed.
- Replaying a completed copy does not invoke materialization again.

---

### Task 5: Implement dataset-specific materializers

**Objective:** Preserve public constrained-off, forecast, generation, and asset identity facts without mixing grains.

**Files:**
- Refactor: `backend/src/curtailess/materialization.py`
- Create: `backend/src/curtailess/materializers/__init__.py`
- Create: `backend/src/curtailess/materializers/constrained_off.py`
- Create: `backend/src/curtailess/materializers/forecast.py`
- Create: `backend/src/curtailess/materializers/generation.py`
- Create: `backend/src/curtailess/materializers/assets.py`
- Create matching tests under `backend/tests/`
- Modify: `backend/src/curtailess/data_access.py`
- Modify: `template.yaml`

**Constrained-off facts:**

- `val_geracao`
- `val_disponibilidade`
- `val_geracaolimitada`
- `val_geracaoreferencia`
- `val_geracaonaorealizadaapurada`
- restriction reason and origin
- connection and asset identifiers
- coverage, null, duplicate, and unknown-reason counts

Support wind and photovoltaic sources through one shared transformation. Preserve `PAR`, null reasons, and unknown codes without losing total energy.

**Forecast facts:**

- publication/run timestamp
- valid timestamp
- forecast and programmed generation
- identity/grain metadata
- deterministic latest-publication-for-valid-instant rule

**Generation facts:**

- hourly observed generation profiles by asset and period
- seasonal and hour-of-day aggregates

**Identity facts:**

- effective-dated mapping level
- plant, ONS group, program entity, connection point, technology, capacity, and validity

Keep large interval facts in curated S3 Parquet. Store compact catalogs, aggregates, and current snapshots in DynamoDB. Reconcile corrected periods by removing obsolete items.

---

### Task 6: Add deterministic simulated current plant state

**Objective:** Estimate current plant values from fresh public inputs and public historical distributions without claiming live private SCADA.

**Files:**
- Create: `backend/src/curtailess/plant_state.py`
- Modify: `backend/src/curtailess/data_access.py`
- Modify: `backend/src/curtailess/schemas.py`
- Modify: `backend/src/curtailess/main.py`
- Create: `backend/tests/test_plant_state.py`
- Modify: `backend/tests/test_data_access.py`
- Modify: `backend/tests/test_api.py`
- Modify: `template.yaml`

**Endpoint:**

```text
GET /v1/assets/{asset_id}/plant-state?as_of=<RFC3339>
```

Optional overrides use a separate POST and require `CLIENTE_INFORMADO` provenance.

**Algorithm:**

1. Resolve identity valid at `as_of`.
2. Select a fresh public forecast/programming record covering `as_of`.
3. Derive public historical distributions for generation/reference ratio, availability ratio, seasonal generation, and curtailed residuals.
4. Apply fallback order `asset -> ONS group or connection point -> technology and state`.
5. Generate deterministic synthetic state using a seed from asset, normalized `as_of`, source snapshot IDs, and algorithm version.
6. Clamp generation, availability, reference, and limit values to non-negative public physical bounds.
7. Persist the exact snapshot by deterministic snapshot ID.

**Status rules:**

- Direct public observations: `ONS_PUBLICO`.
- Distributions, calibrated baselines, and residual calculations: `PROXY_CALCULADO`.
- Estimated current generation, availability, reference, or limit: `SIMULADO`.
- User override: `CLIENTE_INFORMADO`.
- Missing fresh public current input: `REVIEW_REQUIRED`.

**Tests:**

- Equal inputs produce byte-equivalent facts.
- Different source snapshots change the snapshot ID.
- Fallback level is recorded.
- Capacity and non-negative clamps.
- Stale forecast returns review required.
- No output calls simulated values measured/current SCADA.

---

### Task 7: Implement deterministic multi-day eligibility and ranking

**Objective:** Replace monthly-prorated demonstration ranking with candidate generation, rejection reasons, complete metrics, and stable ordering.

**Files:**
- Create: `backend/src/curtailess/maintenance.py`
- Modify: `backend/src/curtailess/schemas.py`
- Modify: `backend/src/curtailess/data_access.py`
- Modify: `backend/src/curtailess/main.py`
- Create: `backend/tests/test_maintenance.py`
- Modify: `backend/tests/test_api.py`

**Pure functions:**

- `generate_candidate_windows`
- `evaluate_eligibility`
- `calculate_candidate_metrics`
- `rank_eligible_windows`
- `select_backend_window`

**Eligibility:** duration fit, full-window horizon fit, minimum notice, deadline, unavailable periods, team/resource availability, operational restrictions, source freshness, weather coverage, and uncertainty threshold.

**Metrics:** expected generation, expected curtailment, residual saleable energy, curtailment risk, uncertainty, opportunity cost, operational/data risk, and deadline distance.

**Stable rank tuple:**

1. residual saleable energy ascending;
2. curtailment risk descending;
3. uncertainty ascending;
4. opportunity cost ascending;
5. operational/data risk ascending;
6. deadline distance ascending;
7. UTC start and candidate ID ascending.

Use timezone-aware half-open intervals and `Decimal` for energy and monetary calculations.

---

### Task 8: Add idempotent final decisions and bounded Bedrock explanations

**Objective:** Deliver and store a final backend-selected decision while using Bedrock only for structured explanation.

**Files:**
- Create: `backend/src/curtailess/decisions.py`
- Modify: `backend/src/curtailess/bedrock.py`
- Modify: `backend/src/curtailess/config.py`
- Modify: `backend/src/curtailess/schemas.py`
- Modify: `backend/src/curtailess/main.py`
- Create: `backend/tests/test_decisions.py`
- Modify: `backend/tests/test_bedrock.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/.env.example`
- Modify: `template.yaml`

**Endpoints:**

```text
POST /v1/maintenance/decisions
GET /v1/maintenance/decisions/{decision_id}
```

**Statuses:** `SELECTED`, `NO_ELIGIBLE_WINDOW`, `REVIEW_REQUIRED`.

**Idempotency:** canonical request SHA-256, conditional DynamoDB write, exact stored replay for equal input, HTTP 409 for reused ID with different input, and conditional-race readback.

**Bedrock rules:**

- Send one allowed slot in `BACKEND_SELECTED` mode.
- Send reason codes, fact references, and limitations only.
- Use Converse with explicit `maxTokens` and adaptive retries.
- Request Structured Outputs when the deployed model supports it.
- Validate strict local Pydantic output.
- Reject unknown keys, wrong slot, unknown fact references, and numeric literals in generated prose.
- Fall back to a deterministic explanation without changing the selected slot.
- Record model attempts, prompt/schema versions, validation result, and delivery mode.

**Audit:** Store evaluation time, source snapshots, forecast validity, versions, all candidates, all rejections, immutable Bedrock input, validated output or failure category, final response, and field-level provenance.

---

### Task 9: Connect the frontend to decision-first production flow

**Objective:** Remove fixture-backed maintenance behavior from the production path and present the final decision before details.

**Files:**
- Modify: `frontend/app/domain/types.ts`
- Modify: `frontend/app/domain/api-client.ts`
- Modify: `frontend/app/domain/api-client.test.ts`
- Modify: `frontend/app/state/analysis-context-value.ts`
- Modify: `frontend/app/state/analysis-context.tsx`
- Modify: `frontend/app/features/maintenance/maintenance-screen.tsx`
- Modify: `frontend/app/features/maintenance/maintenance-ranking.tsx`
- Modify: `frontend/app/features/maintenance/intervention-form.tsx`
- Modify: `frontend/app/components/evidence/evidence.tsx`
- Add or modify focused Vitest component/domain tests
- Modify: `frontend/tests/e2e/main-flow.spec.ts`

**Rendered order:**

1. final decision or blocking status;
2. explanation;
3. decisive facts and provenance;
4. limitations, simulation labels, and ONS-approval disclaimer;
5. complete ranking and rejected candidates.

The production path must call the deployed API. Manual candidate selection is removed. Confirmation is disabled for `NO_ELIGIBLE_WINDOW` and `REVIEW_REQUIRED`.

---

### Task 10: Complete infrastructure, documentation, and local deployment

**Objective:** Deploy the complete flow to `curtailess-dev`, seed verified historical data, and prove live behavior.

**Files:**
- Modify: `template.yaml`
- Modify: `samconfig.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/aws-deployment.md`
- Modify: `backend/README.md`
- Modify: `frontend/README.md`
- Modify: `README.md`

**Preflight:**

```bash
aws sts get-caller-identity --profile curtailess-hackathon
aws cloudformation describe-stacks --stack-name curtailess-dev --region us-west-2 --profile curtailess-hackathon
sam --version
```

Stop if the account, region, stack, or credentials differ from the verified hackathon deployment.

**Deploy:**

```bash
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml --cached --parallel
sam deploy --profile curtailess-hackathon
cd frontend
AWS_PROFILE=curtailess-hackathon ./scripts/deploy-s3.sh curtailess-dev us-west-2
```

**Data rollout:**

1. Keep the daily schedule disabled.
2. Run a bounded wind backfill.
3. Rerun the same backfill and verify no-op behavior.
4. Add bounded solar, generation, forecast, and identity backfills only after schema verification.
5. Run incremental discovery twice and verify the second run creates no new materialization.
6. Enable the schedule only after ledger, S3 object count, DynamoDB counts, SQS, and DLQ checks pass.

**Live smoke tests:**

- Stack is `UPDATE_COMPLETE`.
- API health and OpenAPI return HTTP 200.
- Assets include verified technology and provenance.
- Plant-state endpoint returns simulated state with fresh public input references.
- Decision POST returns a final status.
- Equal replay returns the exact stored decision.
- Reused decision ID with changed input returns 409.
- Bedrock failure path preserves the selected slot.
- Frontend displays the final decision before ranking.
- SQS drains and DLQs remain empty.
- No output claims private live SCADA or ONS approval.

---

## Execution strategy

Use at most three subagents concurrently, divided by non-overlapping workstreams:

1. data ingestion, materialization, and plant state;
2. ranking, decision storage, Bedrock, and API;
3. frontend, infrastructure contracts, documentation, and deployment verification.

Serialize any edits to shared files: `schemas.py`, `main.py`, `template.yaml`, and shared tests. Require spec compliance review before code-quality review for each logic-bearing workstream. The parent integrates, runs the complete suite, deploys locally, and verifies live state.

## Safety gates

- Do not enable the daily scheduler before duplicate replay is proven as a no-op.
- Do not deploy with failing local tests or SAM validation.
- Do not delete or replace retained buckets/tables.
- Do not expose AWS credentials in files, logs, commits, or chat.
- Do not mutate raw ONS source objects.
- Do not label simulated current plant values as measurements.
- Do not allow Bedrock output to modify slot, dates, energy, cost, eligibility, or rank.
- Do not claim completion until the deployed API and frontend are read back and tested.
