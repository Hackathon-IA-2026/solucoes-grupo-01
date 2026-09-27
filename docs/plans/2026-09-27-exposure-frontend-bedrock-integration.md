# Exposure Frontend and Bedrock Narrative Integration Plan

> **For Hermes:** Execute this plan directly, task by task, with focused RED/GREEN verification and frequent commits. Do not use subagents because the user requested direct execution.

**Goal:** Replace the repository frontend with the approved six-section version, connect only Exposure to real backend data for five demonstrative individual plants, and materialize bounded interpretation texts through Amazon Bedrock without invoking a model on page load.

**Architecture:** A single `GET /v1/assets/{asset_id}/exposure-view` response carries one coherent deterministic Exposure bundle plus a stored or deterministic six-section narrative. A validated forecast importer and a dedicated DynamoDB narrative repository support explicit local materialization commands. The frontend validates the response with Zod, keeps Exposure selection separate from Maintenance and Battery, and preserves the approved visual structure.

**Plant-level migration:** the Exposure entity is the individual plant, not the generation group. The five selectable identifiers are `RNEM13`, `BAEA52`, `BAEB0B`, `RNMVS2`, and `PBLZ3`, verified in the public ONS registry. Generation groups (`CJU_*`) are systemic context and are never selectable. The view adds `point_context` and `simulated_telemetry`, and the forecast carries potential generation, accepted envelope, scheduled maintenance relief, avoided curtailment, and three non-overlapping 72-hour windows. Verified values and method are in `docs/audits/2026-09-27-granularidade-por-usina-e-narrativas-ia.md`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, boto3 Bedrock Converse, DynamoDB, AWS SAM, React 19, React Router 8, TypeScript 5.9, Zod, Recharts, Vitest, Playwright.

**Design:** `docs/superpowers/specs/2026-09-27-exposure-frontend-bedrock-design.md`

**Verified baseline:** Backend Ruff and 351 tests pass. Replacement frontend TypeScript, ESLint, 31 unit tests, and production build pass.

---

### Task 1: Copy the approved frontend baseline safely

**Objective:** Replace the target frontend source with the approved replacement while preserving target-only deployment files and excluding generated directories.

**Files:**
- Copy from: `/run/media/carloshnp/D/Programming/hackaton-coppe-ia-11092026/curtailless-frontend/`
- Modify: `frontend/app/**`
- Modify: `frontend/tests/e2e/main-flow.spec.ts`
- Preserve: `frontend/scripts/deploy-s3.sh`
- Preserve: `frontend/.env.example`
- Exclude: `node_modules/`, `build/`, `coverage/`, `test-results/`, `HANDOFF-FRONTEND.md`

**Step 1: Record the target status**

Run:

```bash
git status --short
```

Expected: clean worktree before the copy.

**Step 2: Copy the approved files**

Run `rsync` with explicit exclusions and without `--delete` for target-only operational files. Remove only files the handoff explicitly supersedes after the copy.

**Step 3: Verify the copied baseline**

Run:

```bash
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

Expected: 31 unit tests pass and the production build succeeds.

**Step 4: Commit**

```bash
git add frontend

git commit -m "feat(frontend): adopt six-section exposure experience"
```

---

### Task 2: Define the backend Exposure contracts

**Objective:** Add strict Pydantic contracts for the five-plant catalog, all six deterministic data sections, narrative content, and the complete Exposure view.

**Files:**
- Modify: `backend/src/curtailess/schemas.py`
- Create: `backend/tests/test_exposure_view.py`

**Step 1: Write failing schema tests**

Cover:

- exactly five approved plant identifiers, no `CJU_*` group;
- finite values only;
- offset-aware `last_data_update`;
- exactly 60 ordered forecast dates when a forecast is present;
- lower bound not greater than expected or upper bound;
- exactly six narrative keys;
- bounded non-empty narrative paragraphs;
- explicit demonstrative forecast status.

**Step 2: Verify RED**

```bash
cd backend
uv run pytest -q tests/test_exposure_view.py
```

Expected: collection or import failure because the contracts do not exist.

**Step 3: Implement minimal schemas**

Add immutable response models for:

```text
ExposureAssetSummary
ExposureMetric
ExposureDistributionPoint
ExposureForecastPoint
ExposureForecastWindow
ExposureForecast60d
ExposureObservedImpact
ExposureAssociatedConditions
ExposureRecurrence
ExposureQuality
ExposureNarrative
ExposureViewResponse
```

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_view.py
uv run ruff check src/curtailess/schemas.py tests/test_exposure_view.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/schemas.py backend/tests/test_exposure_view.py
git commit -m "feat(exposure): define six-section API contract"
```

---

### Task 3: Import the approved five-asset forecast artifact

**Objective:** Validate the strategy artifact and convert only runtime forecast fields into canonical application records without creating a runtime dependency on the strategy workspace.

**Files:**
- Create: `backend/src/curtailess/exposure_forecast_import.py`
- Create: `backend/tests/test_exposure_forecast_import.py`
- Create: `backend/tests/fixtures/five_asset_forecast_minimal.json`
- Modify: `backend/src/curtailess/config.py`

**Step 1: Write failing importer tests**

Cover:

- artifact schema allowlist;
- exact approved asset set;
- 60 daily forecasts per asset;
- ISO date order;
- finite expected, lower, upper, and probability values;
- interval ordering;
- deterministic canonical digest;
- idempotent repeated import;
- rejection before any write for malformed input.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_exposure_forecast_import.py
```

Expected: module import failure.

**Step 3: Implement validation and canonical extraction**

The importer reads a provided local path or S3 object, validates the full source before writing, then writes compact canonical records through a repository interface. It records source digest and import time.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_forecast_import.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/exposure_forecast_import.py backend/src/curtailess/config.py backend/tests/test_exposure_forecast_import.py backend/tests/fixtures/five_asset_forecast_minimal.json
git commit -m "feat(exposure): import five-asset forecast artifact"
```

---

### Task 4: Assemble the deterministic six-section Exposure bundle

**Objective:** Build one canonical input bundle from public historical facts, simulated plant state, imported forecasts, connection context, and data-quality facts.

**Files:**
- Create: `backend/src/curtailess/exposure_view.py`
- Modify: `backend/src/curtailess/data_access.py`
- Modify: `backend/tests/test_data_access.py`
- Modify: `backend/tests/test_exposure_view.py`

**Step 1: Write failing assembly tests**

Use representative wind and solar inputs. Assert:

- section 1 asset metadata and latest materialization timestamp;
- section 2 observed impact metrics;
- section 3 60-day series, accumulated interval, and stable top-three periods;
- section 4 reason, reach, and optional modality distributions;
- section 5 weekday and local-hour recurrence;
- section 6 shared/exclusive split and quality indicators;
- canonical input digest stability;
- no unsupported causal or physical-limit field.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_exposure_view.py tests/test_data_access.py
```

**Step 3: Implement repository queries and assembly**

Keep derivations deterministic and bounded. Normalize recurrence to `America/Sao_Paulo`. Return missing optional sections explicitly rather than substituting another asset.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_view.py tests/test_data_access.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/exposure_view.py backend/src/curtailess/data_access.py backend/tests/test_exposure_view.py backend/tests/test_data_access.py
git commit -m "feat(exposure): assemble deterministic asset view"
```

---

### Task 5: Validate and generate six Bedrock narrative sections

**Objective:** Generate interpretation text only, reject unsupported claims, and provide deterministic current-bundle fallback text.

**Files:**
- Modify: `backend/src/curtailess/bedrock.py`
- Create: `backend/src/curtailess/exposure_narrative.py`
- Modify: `backend/tests/test_bedrock.py`
- Create: `backend/tests/test_exposure_narrative.py`

**Step 1: Write failing tests**

Cover:

- valid six-section JSON;
- missing and extra keys;
- paragraph count and length bounds;
- a number absent from the evidence bundle;
- unit alteration;
- causal claim;
- operationally validated forecast claim;
- Operador Nacional do Sistema Elétrico approval or coordination claim;
- maintenance or battery recommendation;
- internal source or prompt disclosure;
- primary, fallback, emergency, and all-model-failure paths;
- deterministic fallback for wind and solar.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_exposure_narrative.py tests/test_bedrock.py
```

**Step 3: Implement the bounded generator**

Use Bedrock Converse through `bedrock-runtime`, adaptive retry mode, explicit `maxTokens`, no tools, and no unsupported `temperature`. Send only canonical Exposure facts. Parse and validate JSON before returning a narrative.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_narrative.py tests/test_bedrock.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/bedrock.py backend/src/curtailess/exposure_narrative.py backend/tests/test_bedrock.py backend/tests/test_exposure_narrative.py
git commit -m "feat(exposure): generate bounded Bedrock narratives"
```

---

### Task 6: Persist versioned narratives safely

**Objective:** Store immutable narrative versions and update the current pointer only after successful validation.

**Files:**
- Create: `backend/src/curtailess/exposure_narrative_repository.py`
- Create: `backend/tests/test_exposure_narrative_repository.py`
- Modify: `backend/src/curtailess/config.py`

**Step 1: Write failing repository tests**

Cover:

- conditional immutable version write;
- idempotent replay;
- current pointer update after version persistence;
- no pointer update after failure;
- exact-digest retrieval;
- last-valid retrieval;
- response digest verification;
- size bound below DynamoDB item limits.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_exposure_narrative_repository.py
```

**Step 3: Implement DynamoDB and in-memory repositories**

Use:

```text
PK = ASSET#{asset_id}
SK = VERSION#{schema_version}#{input_digest}
SK = CURRENT
```

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_narrative_repository.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/exposure_narrative_repository.py backend/src/curtailess/config.py backend/tests/test_exposure_narrative_repository.py
git commit -m "feat(exposure): persist validated narratives"
```

---

### Task 7: Add explicit forecast and narrative materialization commands

**Objective:** Provide auditable commands for importing forecast data and generating narratives without adding a schedule.

**Files:**
- Create: `backend/src/curtailess/materialize_exposure_forecast.py`
- Create: `backend/src/curtailess/materialize_exposure_narratives.py`
- Create: `backend/tests/test_exposure_commands.py`
- Modify: `backend/README.md`

**Step 1: Write failing CLI tests**

Cover `--help`, `--asset-id`, `--all`, invalid mutual combinations, no-op import, and nonzero exit on validation failure.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_exposure_commands.py
```

**Step 3: Implement commands**

Commands read settings and use dependency-injected services. They print identifiers and statuses only, never credentials, prompts, or raw model responses.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_exposure_commands.py
uv run python -m curtailess.materialize_exposure_forecast --help
uv run python -m curtailess.materialize_exposure_narratives --help
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/materialize_exposure_forecast.py backend/src/curtailess/materialize_exposure_narratives.py backend/tests/test_exposure_commands.py backend/README.md
git commit -m "feat(exposure): add explicit materialization commands"
```

---

### Task 8: Expose the coherent Exposure API

**Objective:** Serve the five-plant catalog and complete Exposure view with stored, compatible, or deterministic narrative selection.

**Files:**
- Modify: `backend/src/curtailess/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/tests/test_exposure_view.py`

**Step 1: Write failing endpoint tests**

Cover:

- five approved individual plants, no `CJU_*` group selectable;
- successful wind and solar views;
- exact narrative match;
- compatible previous narrative;
- deterministic fallback;
- unknown asset 404;
- missing forecast response;
- malformed storage record failure without cross-asset fallback.

**Step 2: Verify RED**

```bash
uv run pytest -q tests/test_api.py tests/test_exposure_view.py
```

**Step 3: Implement endpoints and selection order**

Serve one immutable package. Exclude model, prompt, source key, and source hash metadata from the public response.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_api.py tests/test_exposure_view.py
```

**Step 5: Commit**

```bash
git add backend/src/curtailess/main.py backend/tests/test_api.py backend/tests/test_exposure_view.py
git commit -m "feat(api): serve materialized exposure views"
```

---

### Task 9: Add retained narrative infrastructure

**Objective:** Add the dedicated DynamoDB table, environment variables, and least-required Lambda permissions without deploying.

**Files:**
- Modify: `template.yaml`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_infrastructure_contract.py`

**Step 1: Write failing infrastructure tests**

Assert:

- on-demand billing;
- managed encryption;
- point-in-time recovery;
- retention policies;
- table name environment variable;
- API read permission;
- materializer write and Bedrock permissions where applicable;
- no EventBridge or Scheduler resource.

**Step 2: Verify RED**

```bash
cd backend
uv run pytest -q tests/test_infrastructure_contract.py
```

**Step 3: Implement SAM resources**

Add only the narrative table and required configuration. Do not add a recurring trigger.

**Step 4: Verify GREEN**

```bash
uv run pytest -q tests/test_infrastructure_contract.py
cd ..
sam validate --lint
sam build
```

**Step 5: Commit**

```bash
git add template.yaml backend/.env.example backend/tests/test_infrastructure_contract.py
git commit -m "feat(infra): provision retained exposure narratives"
```

---

### Task 10: Add the typed frontend Exposure client

**Objective:** Validate the real asset catalog and Exposure package at the browser boundary without fixture substitution.

**Files:**
- Create: `frontend/app/domain/exposure-api.ts`
- Create: `frontend/app/domain/exposure-api.test.ts`
- Modify: `frontend/app/domain/types.ts`
- Modify: `frontend/.env.example`

**Step 1: Write failing client tests**

Cover:

- valid catalog and complete view;
- malformed six-section narrative;
- malformed forecast interval;
- HTTP errors;
- missing base URL;
- abort propagation;
- no fixture fallback.

**Step 2: Verify RED**

```bash
cd frontend
npm test -- --run app/domain/exposure-api.test.ts
```

**Step 3: Implement Zod schemas and client**

Keep schemas at the response boundary and map snake_case API fields once. Fetch the complete Exposure package in one request.

**Step 4: Verify GREEN**

```bash
npm test -- --run app/domain/exposure-api.test.ts
npm run typecheck
```

**Step 5: Commit**

```bash
git add frontend/app/domain/exposure-api.ts frontend/app/domain/exposure-api.test.ts frontend/app/domain/types.ts frontend/.env.example
git commit -m "feat(frontend): validate exposure API responses"
```

---

### Task 11: Isolate real Exposure selection

**Objective:** Load and switch five real assets on Exposure without changing Maintenance or Battery state.

**Files:**
- Modify: `frontend/app/state/analysis-context-value.ts`
- Modify: `frontend/app/state/analysis-context.tsx`
- Modify: `frontend/app/components/layout/asset-picker.tsx`
- Modify: `frontend/app/components/layout/app-shell.tsx`
- Create: `frontend/app/state/exposure-context.tsx`
- Create: `frontend/app/state/exposure-context.test.tsx`

**Step 1: Write failing state tests**

Cover:

- catalog load;
- default first approved asset;
- Exposure-only selection;
- no change to demonstration `assetId`;
- stale response ignored or aborted;
- loading and HTTP failure;
- unknown selection rejected.

**Step 2: Verify RED**

```bash
npm test -- --run app/state/exposure-context.test.tsx
```

**Step 3: Implement route-scoped context and picker mode**

The top-bar picker reads Exposure context only on `/exposicao`. Other routes continue using the copied demonstration context.

**Step 4: Verify GREEN**

```bash
npm test -- --run app/state/exposure-context.test.tsx
npm run typecheck
```

**Step 5: Commit**

```bash
git add frontend/app/state frontend/app/components/layout/asset-picker.tsx frontend/app/components/layout/app-shell.tsx
git commit -m "feat(frontend): isolate exposure asset selection"
```

---

### Task 12: Connect all six Exposure sections

**Objective:** Render backend facts and stored narratives in the approved frontend structure while preserving chart patterns and visual rules.

**Files:**
- Modify: `frontend/app/features/exposure/exposure-screen.tsx`
- Remove after replacement: `frontend/app/features/exposure/exposure-narrative.ts`
- Modify: `frontend/app/components/charts/exposure-charts.tsx`
- Modify: `frontend/app/components/layout/asset-context.tsx`
- Modify: `frontend/app/components/topology/asset-topology.tsx`
- Modify: `frontend/app/components/evidence/highlight-list.tsx` only if required by actual API nullability
- Modify: `frontend/tests/e2e/main-flow.spec.ts`
- Create: `frontend/app/features/exposure/exposure-screen.test.tsx`

**Step 1: Write failing screen tests**

Assert:

- exactly six sections;
- six backend narrative arrays rendered;
- last data update in section 1;
- actual metrics and forecast series mapped;
- no provenance panel;
- no call to action;
- no local narrative builder import;
- partial metric handling;
- no forecast handling;
- full API failure handling.

**Step 2: Verify RED**

```bash
npm test -- --run app/features/exposure/exposure-screen.test.tsx
```

**Step 3: Implement the connected screen**

Keep `AnalysisSection`, `SectionNav`, illustration wrappers, chart slots, chart/table switching, typography, spacing, and z-index rules. Adapt chart aggregation and labels to the daily backend series.

**Step 4: Verify GREEN**

```bash
npm test -- --run app/features/exposure/exposure-screen.test.tsx
npm run typecheck
npm run lint
```

**Step 5: Commit**

```bash
git add frontend/app/features/exposure frontend/app/components frontend/tests/e2e/main-flow.spec.ts
git commit -m "feat(frontend): connect six-section exposure view"
```

---

### Task 13: Verify the complete local system

**Objective:** Prove backend, frontend, infrastructure translation, and rendered behavior before any deployment.

**Files:**
- Modify only defects proven by the gates below.

**Step 1: Run backend gates**

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv run pytest -q
uv run python -m curtailess.materialize_exposure_forecast --help
uv run python -m curtailess.materialize_exposure_narratives --help
```

**Step 2: Run infrastructure gates**

```bash
cd ..
git diff --check
sam validate --lint
sam build
```

**Step 3: Run frontend gates**

```bash
cd frontend
npm ci
npm run typecheck
npm run lint
npm test -- --run
npm run build
npx playwright test
```

**Step 4: Inspect rendering**

Run the frontend against a local backend or deterministic test server. Inspect desktop and 375 px widths. Verify six sections, five assets, backend narratives, chart/table switching, sticky header, top-bar offset, wheel navigation, keyboard behavior, reduced motion, illustration layering, and zero horizontal overflow.

**Step 5: Confirm deployment boundary**

Do not run:

```text
sam deploy
AWS forecast import
AWS narrative materialization
S3 frontend publication
```

**Step 6: Commit final verified fixes**

```bash
git add -u
git commit -m "test(exposure): verify connected frontend flow"
```

**Step 7: Handoff**

Report:

- commits;
- changed components;
- backend and frontend test counts;
- SAM validation and build status;
- exact local commands for the user to run;
- known limitations;
- confirmation that no deployment or AWS write occurred.

---

## Plant-level supersession

The five-asset group-level contract in Tasks 2, 3, 4, and 8 was superseded by the individual plant contract through commits `b813a04`, `c03fe81`, `fd54b60`, `86f022b`, `2520168`, `1e9f540`, `de32cd3`, `fbf1323`, and `e77d6a5`. The current contract:

- selects exactly five individual plants, `RNEM13`, `BAEA52`, `BAEB0B`, `RNMVS2`, and `PBLZ3`, one per current context;
- never exposes a `CJU_*` generation group as a selectable asset;
- reconciles the individual energy against the published group total and conserves it within 1e-6 MWh;
- simulates every plant connected to the point and estimates point pressure without double counting;
- compares a scenario without scheduled maintenance, a scenario with scheduled maintenance, and the candidate 72-hour window counterfactual, all over the same weather samples;
- publishes exactly 60 daily points and three non-overlapping 72-hour windows;
- validates each Bedrock section only against its own evidence subset and falls back per section.

The corrected solar point envelopes from commit `fbf1323` (deduplicated aggregate source and technology-restricted published series) and all verified plant-level values are documented in `docs/audits/2026-09-27-granularidade-por-usina-e-narrativas-ia.md`.

The product surface still shows no provenance panel and no call to action, and Exposure selection is not propagated to Maintenance, Battery, or Report.
