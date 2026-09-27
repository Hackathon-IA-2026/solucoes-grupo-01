# Exposure Frontend and Materialized Bedrock Narratives

## Status

Approved design for replacing the current CurtaiLess frontend baseline and connecting only the Exposure route to backend data and stored Amazon Bedrock narratives.

## Context

The replacement frontend is located at:

```text
/run/media/carloshnp/D/Programming/hackaton-coppe-ia-11092026/curtailless-frontend
```

The target frontend is located at:

```text
/run/media/carloshnp/D/Programming/CurtaiLess/frontend
```

`HANDOFF-FRONTEND.md` in the replacement directory defines the accepted visual and behavioral baseline. The replacement Exposure route has six viewport-sized sections, a sticky top bar, route-local section navigation, wind and solar illustrations, and a three-column desktop layout. Its current data and narratives come from local fixtures.

The backend already materializes public Operador Nacional do Sistema Elétrico data, simulates plant state, ranks maintenance windows deterministically, and uses Bedrock only for bounded explanations. A separate forecasting artifact contains a demonstrative 60-day forecast for five representative wind and solar groups.

## Goals

1. Copy the replacement frontend into the CurtaiLess repository without moving or modifying the source directory.
2. Preserve the replacement frontend's visual structure and interaction rules.
3. Connect only the Exposure route to backend data.
4. Replace Exposure fixtures with one coherent backend response per selected asset.
5. Expose the five demonstrative assets:
   - `CJU_RNRDV`
   - `CJU_BALRA`
   - `CJU_BASDB`
   - `CJU_RNMVS`
   - `CJU_PBLZA`
6. Materialize the six central interpretation texts with models available through Amazon Bedrock.
7. Store validated narratives in AWS so page refreshes never invoke Bedrock.
8. Keep deterministic fallback text available when no compatible validated narrative exists.
9. Stop verification at local tests and `sam build`. Deployment and AWS data writes require separate authorization.

## Non-goals

- Connecting or redesigning Maintenance.
- Connecting or redesigning Battery.
- Connecting or redesigning Report.
- Passing the selected Exposure asset into Maintenance or Battery.
- Adding a call to action at the end of Exposure.
- Displaying internal provenance, source object keys, source hashes, prompt versions, or model identifiers to the customer.
- Presenting private Supervisory Control and Data Acquisition data as available.
- Claiming an operationally validated forecast.
- Claiming approval, validation, or coordination by the Operador Nacional do Sistema Elétrico.
- Adding EventBridge, Scheduler, or another recurring generation pipeline in this phase.
- Deploying the stack or publishing the frontend.

## Product behavior

### Exposure structure

The Exposure route keeps exactly six sections:

1. Where the plant is connected.
2. Observed impact on the plant.
3. Curtailment forecast for the next 60 days.
4. Conditions associated with curtailment.
5. Days and hours with the highest recurrence.
6. Pattern reach and data quality.

Each desktop section keeps three equal columns:

1. asset and network illustration;
2. interpretation text;
3. deterministic metrics, chart, table, or quality evidence.

The illustration remains hidden below the existing `xl` breakpoint. Section navigation remains hidden below the existing `lg` breakpoint.

### Customer-facing technical detail

The main Exposure surface does not show:

- source names;
- ingestion methods;
- data versions;
- source hashes;
- calculated or measured badges;
- repeated technical periods;
- a provenance drill-down.

Data quality remains customer-facing because it changes how a reader interprets the results. Internal data lineage remains available in backend records and logs.

### Data update time

Section 1 shows `Last data update`. The displayed timestamp is the newest materialization timestamp among the facts included in the response package. The screen does not introduce a separate operational reference timestamp.

The timestamp must be returned as an offset-aware ISO 8601 value and formatted for `America/Sao_Paulo` in the frontend.

### Forecast language

The 60-day result remains a demonstrative scenario. The interface calls uncertainty bounds an estimated range. It does not advertise 90% coverage because existing backtests do not support uniform 90% daily empirical coverage across the portfolio.

## Frontend migration

Copy source, configuration, tests, and dependency manifests from the replacement directory. Do not copy:

- `node_modules/`;
- `build/`;
- `test-results/`;
- temporary files;
- `HANDOFF-FRONTEND.md`.

Preserve target-only operational files such as the S3 publishing script and environment example unless a reviewed integration change requires an update.

The copied Maintenance, Battery, and Report screens become the target baseline but receive no new backend integration in this phase.

## Exposure selection isolation

The replacement frontend currently shares one `assetId` across Exposure, Maintenance, and Battery. Real Exposure identifiers would trigger misleading fixture fallbacks in the other routes.

Add route-scoped Exposure state:

```text
exposureAssetId
exposureAssets
exposureView
exposureStatus
exposureError
selectionRevision
```

On `/exposicao`, the top-bar asset picker reads the five real demonstrative assets and writes only `exposureAssetId`. Other routes retain the replacement frontend's existing demonstration state until those routes are redesigned.

An Exposure selection change must:

1. increment a revision or request identity;
2. retain the six-section layout while loading;
3. fetch the selected asset package;
4. replace data, illustration, charts, and narrative together;
5. ignore late responses for a previous asset.

Unknown assets return HTTP 404. No route silently falls back to another asset.

## Backend API

### Asset catalog

The Exposure picker uses an endpoint that returns the five approved demonstration assets. The response includes only fields required by the picker and illustrations:

```json
{
  "items": [
    {
      "asset_id": "CJU_RNRDV",
      "name": "Conj. Rio do Vento",
      "technology": "wind",
      "state": "RN",
      "connection_point": "RNCMM-500-A",
      "capacity_mw": 0,
      "connected_asset_count": 0,
      "operational_data_status": "simulated"
    }
  ]
}
```

The example values are structural placeholders. Tests must use computed fixture values rather than treating those numbers as product facts.

### Exposure view

Add:

```text
GET /v1/assets/{asset_id}/exposure-view
```

The endpoint returns one immutable response package assembled from a coherent deterministic input bundle. It includes:

```text
asset
last_data_update
input_digest
observed_impact
forecast_60d
associated_conditions
recurrence
pattern_reach
quality
narrative
limitations
```

The frontend must not join several independently timed API responses into one Exposure screen.

### Section 1: asset

Return:

- asset identifier;
- display name;
- wind or solar technology;
- state;
- connection point;
- installed capacity;
- number of associated plants or groups;
- operational data status;
- last data update.

### Section 2: observed impact

Return:

- historically curtailed energy;
- share with a characterized reason;
- share simultaneous with other assets at the point;
- share exclusive to the selected asset;
- covered historical period.

### Section 3: 60-day forecast

Return:

- one point per forecast date;
- expected curtailed energy;
- lower and upper estimated bounds;
- estimated curtailment probability;
- accumulated 60-day expected energy and bounds;
- the three periods with the highest exposure according to a deterministic ranking;
- forecast start and end dates;
- an explicit demonstrative status.

The UI may aggregate daily points for visual readability, but the table preserves exact daily values.

### Section 4: associated conditions

Return deterministic distributions for:

- recorded reason;
- systemic, local, or unreported reach;
- restriction modality when the technology and source provide it.

The response describes association only. It does not state that a recorded condition caused a curtailment event.

### Section 5: recurrence

Return:

- recurrence by weekday;
- recurrence by local hour bucket;
- timezone `America/Sao_Paulo`.

### Section 6: pattern reach and quality

Return:

- shared versus asset-exclusive proportions;
- historical coverage;
- update delay;
- missing-record rate;
- duplicate-record count.

### Narrative

Return exactly these keys:

```json
{
  "secao-ativo": ["..."],
  "secao-resumo": ["..."],
  "secao-previsao": ["..."],
  "secao-razao-origem": ["..."],
  "secao-recorrencia": ["..."],
  "secao-qualidade": ["..."]
}
```

Each value contains bounded non-empty paragraphs. Titles, metrics, dates, units, charts, warnings, and limitations remain deterministic.

## Forecast import

The frontend must never read the strategy artifact directly. Add an explicit backend importer that:

1. reads the approved five-asset forecast artifact;
2. validates the artifact schema and approved asset identifiers;
3. validates finite numeric values, dates, intervals, and 60-day cardinality;
4. extracts only runtime fields required by Exposure;
5. writes canonical forecast records to application storage;
6. records the artifact digest and import timestamp;
7. performs an idempotent no-op when the same artifact was already imported.

The implementation may accept a local artifact path for development and an S3 object for AWS execution. Runtime API code reads application storage, not the strategy workspace.

No AWS import is executed without separate authorization.

## Narrative materialization

### Command

Add an explicit command:

```bash
python -m curtailess.materialize_exposure_narratives --asset-id CJU_RNRDV
python -m curtailess.materialize_exposure_narratives --all
```

The command uses configured AWS credentials and region. Documentation examples use:

```text
AWS_PROFILE=curtailess-hackathon
AWS_REGION=us-west-2
```

Credentials never enter source, command arguments, logs, test snapshots, or chat.

### Input bundle

For each asset, build one canonical bundle containing only deterministic facts displayed or interpreted by the Exposure screen. Compute:

```text
input_digest = sha256(canonical_json(bundle))
```

The same bundle and schema version must produce the same digest.

### Bedrock response

Invoke the Bedrock Converse API with explicit `maxTokens` and adaptive retries. Use the configured primary, fallback, and emergency models in order. Do not pass `temperature` to models that reject it.

Request one JSON object containing all six section arrays. One successful model response materializes one asset. The model does not receive tools and cannot write to storage directly.

### Validation

Treat model output as untrusted. Reject output that:

- is not valid JSON;
- has missing or unknown section keys;
- exceeds paragraph or section limits;
- is empty;
- cites a number not present in the canonical input bundle;
- changes a unit;
- claims causality unsupported by the input;
- calls the forecast operationally validated;
- claims Operador Nacional do Sistema Elétrico approval, validation, or coordination;
- recommends maintenance or battery action;
- mentions internal source keys, buckets, hashes, prompt details, or ingestion methods.

Validated narratives store the exact input digest, model identifier, prompt version, narrative schema version, validation result, generation timestamp, and token usage when available. The public API excludes this metadata.

## Deterministic narrative fallback

Port the useful deterministic behavior from the replacement frontend's `exposure-narrative.ts` into a backend formatter that consumes the same canonical input bundle as Bedrock.

The narrative selection order is:

1. validated narrative matching the current input digest and schema version;
2. last validated narrative for the asset, only when compatibility validation proves every cited fact remains valid;
3. deterministic narrative for the current bundle.

If Bedrock generation fails, do not overwrite the current pointer. A failed first generation still leaves the deterministic narrative available.

The public response does not expose Bedrock availability or failure details.

## DynamoDB design

Create a dedicated retained table for Exposure narratives.

Required properties:

- on-demand billing;
- managed encryption;
- point-in-time recovery;
- `DeletionPolicy: Retain`;
- `UpdateReplacePolicy: Retain`.

Logical records:

```text
PK: ASSET#{asset_id}
SK: VERSION#{narrative_schema_version}#{input_digest}
```

Current pointer:

```text
PK: ASSET#{asset_id}
SK: CURRENT
```

Version writes are conditional. The current pointer updates only after complete validation and successful version persistence. Failed generation records may be logged without replacing customer-visible content.

The API function receives read access. The materialization execution path receives the minimum write and Bedrock invocation permissions required by its execution mode.

No schedule is created in this phase. A future schedule can call the same materialization service.

## Frontend data access

Add a typed HTTP client with Zod validation at the response boundary. The client:

- requires `VITE_API_BASE_URL`;
- requests the asset catalog and Exposure package;
- rejects malformed responses;
- does not substitute local fixtures after an HTTP or validation failure;
- supports aborting obsolete requests.

Use parallel requests only when dependencies are independent. Loading an Exposure package remains one request.

## Frontend rendering and error behavior

- Keep all six sections mounted during loading.
- Show section-local skeletons or neutral loading states without changing page geometry.
- A complete API failure shows a bounded unavailable state and no fixture values.
- A missing metric shows `Indisponível` only in the affected component.
- A missing forecast keeps section 3 and explains that the 60-day scenario is unavailable.
- A missing stored narrative uses backend fallback text.
- Stale data remains visible with the actual last update in section 1 and delay in section 6.
- Do not show Bedrock errors to the customer.

## Visual invariants

Preserve the rules in `HANDOFF-FRONTEND.md`:

- exactly six Exposure sections;
- sticky top bar;
- no global left navigation;
- route-local section navigation;
- one wheel gesture advances or returns one section;
- section top aligns with the measured bottom of the top bar;
- `prefers-reduced-motion` is respected;
- desktop sections use three equal columns;
- the main plant stays centered in the illustration column;
- connected plants use the existing irregular layout;
- connections retain two isometric segments and one elbow;
- illustrations never overlap central or right cards;
- no play or pause control;
- no horizontal overflow at 375 px;
- graphs and tables follow the replacement frontend's component patterns.

Charts may change data shape, aggregation, labels, and ranges to represent backend values. Their visual language, card structure, switch behavior, typography, and spacing remain unchanged.

## Security and privacy

- The frontend never calls Bedrock.
- The browser receives no AWS credentials, prompt, model identifier, source hash, or internal object key.
- The Bedrock prompt contains only the bounded Exposure fact bundle.
- Model output cannot choose an asset, query data, call a tool, or perform an operation.
- IAM permissions must be scoped to the new table and required Bedrock actions where supported by the selected inference profiles.
- No private Supervisory Control and Data Acquisition values are invented or implied.

## Testing strategy

### Backend unit tests

Cover:

- forecast artifact validation;
- five approved assets;
- 60-day cardinality and date ordering;
- idempotent forecast import;
- canonical digest stability;
- six-section deterministic bundle assembly;
- narrative JSON validation;
- unknown keys and missing keys;
- unsupported numeric claims;
- prohibited operational claims;
- primary, fallback, and emergency model behavior;
- deterministic first-generation fallback;
- previous-version compatibility checks;
- conditional DynamoDB writes;
- current pointer safety;
- endpoint 200, 404, partial data, and no-forecast behavior.

### Frontend unit tests

Cover:

- Zod response validation;
- five-asset catalog mapping;
- route-scoped Exposure selection;
- stale request rejection or cancellation;
- six section keys;
- metric and chart mapping;
- missing metrics;
- missing forecast;
- loading and complete API failure;
- last update formatting in `America/Sao_Paulo`;
- absence of fixture substitution.

### End-to-end tests

Cover:

- exactly six sections;
- switching among representative wind and solar assets;
- asset-specific narratives and values;
- chart and table switching;
- section navigation by click, keyboard, Escape, and wheel;
- exact top-bar offset;
- sticky header;
- illustration selection and connected-asset count;
- no overflow at 375 px;
- minimum 44 px targets;
- reduced-motion behavior;
- no Exposure selection propagation into Maintenance or Battery;
- direct route loading.

Tests should assert semantic structure and behavior. Tests must not treat generated prose or nonessential fixture values as rigid contracts.

## Verification gates

Run:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python -m curtailess.materialize_exposure_narratives --help
cd ..
sam validate --lint
sam build

cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npx playwright test
```

Inspect the rendered Exposure route at desktop and 375 px widths. Check console errors, geometry, data switching, loading, failures, keyboard behavior, wheel behavior, and reduced motion.

## Deployment boundary

The approved implementation includes local code changes, tests, SAM validation, and SAM build. It excludes:

- `sam deploy`;
- writes to deployed DynamoDB tables;
- forecast import into AWS;
- production Bedrock narrative materialization;
- S3 frontend publication.

Each excluded operation requires separate user authorization after local verification.

## Acceptance criteria

1. The target repository contains the replacement frontend baseline without modifying the source directory.
2. Exposure preserves all six sections and visual invariants.
3. Exposure lists and switches among the five approved demonstration assets.
4. Exposure obtains all customer-visible facts and narratives from the backend.
5. Exposure contains no fixture fallback.
6. Maintenance, Battery, and Report receive no new backend integration.
7. Exposure selection does not contaminate the demonstration state of other routes.
8. Section 1 shows the actual last data update.
9. The main surface contains no internal provenance panel and no call to action.
10. Bedrock generates only the six bounded interpretation texts.
11. Titles, metrics, charts, units, dates, warnings, and limitations remain deterministic.
12. Validated narratives are persistable and replayable by asset and input digest.
13. Failed generation preserves the last compatible text or uses deterministic fallback.
14. No recurring pipeline is added.
15. Backend tests, frontend tests, type checking, linting, builds, SAM validation, and Playwright pass.
16. No deployment or AWS write occurs during implementation without new authorization.
