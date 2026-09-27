import math
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException

from .canonical import canonical_digest as _canonical_digest
from .canonical import canonical_json as _canonical_json
from .provenance_service import (
    field_provenance as _field_provenance,
)
from .provenance_service import (
    persist_operation as _persist_operation,
)
from .provenance_service import (
    validate_caller_provenance as _validate_caller_provenance_impl,
)
from .schemas import (
    MAX_PLANNING_RESULTS,
    BessScreenRequest,
    BessScreenResponse,
    DataOrigin,
    EvidenceProvenance,
    MaintenanceRankRequest,
    MaintenanceRankResponse,
    MonetaryEvidence,
    NumericEvidence,
    Period,
    RankedMaintenanceWindow,
)


def _json_context(kind: str, **values: object) -> str:
    return _canonical_json({"kind": kind, **values})


def _checked_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Valor numérico inválido: {field_name}."
        ) from exc
    if not math.isfinite(result):
        raise HTTPException(
            status_code=422, detail=f"Valor numérico fora do domínio: {field_name}."
        )
    return result


def _checked_multiply(left: float, right: float, field_name: str) -> float:
    return _checked_float(left * right, field_name)


def _checked_subtract(left: float, right: float, field_name: str) -> float:
    return _checked_float(left - right, field_name)


def build_rank_maintenance(
    request: MaintenanceRankRequest, repository: Any, issued_provenance_repository: Any
) -> MaintenanceRankResponse:
    input_provenance = request.input_provenance or {}
    _validate_caller_provenance_impl(input_provenance, issued_provenance_repository)
    asset_item = repository.get_asset(request.asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")

    baseline = request.baseline_window_start
    if baseline.tzinfo is None:
        baseline = baseline.replace(tzinfo=UTC)
    period_start = datetime.combine(request.start, datetime.min.time(), tzinfo=UTC)
    period_end = datetime.combine(request.end, datetime.max.time(), tzinfo=UTC)
    if not period_start <= baseline <= period_end:
        raise HTTPException(status_code=422, detail="Janela-base fora do período informado.")

    candidates = repository.get_historical_windows(
        request.asset_id,
        request.start,
        request.end,
        request.duration_hours,
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="Sem sinal histórico materializado.")
    if len(candidates) > MAX_PLANNING_RESULTS:
        raise HTTPException(
            status_code=422,
            detail=f"Resultado excede o limite de {MAX_PLANNING_RESULTS} janelas.",
        )
    for candidate in candidates:
        candidate["curtailed_mwh"] = _checked_float(
            candidate.get("curtailed_mwh"), "expected_curtailed_energy"
        )

    limitation = (
        "Ranking baseado em taxa mensal histórica materializada do ONS: não é previsão "
        "operacional e não preserva a distribuição intramensal; não coordena nem revela "
        "manutenções de terceiros."
    )
    candidates.sort(key=lambda item: item["curtailed_mwh"], reverse=True)
    baseline_candidate = min(
        candidates,
        key=lambda item: abs(item["start"] - baseline),
    )
    baseline_energy = baseline_candidate["curtailed_mwh"]
    decision_parent_ids = [item.evidence_id for item in input_provenance.values()]

    input_evidence_ids = {
        field_name: provenance.evidence_id for field_name, provenance in input_provenance.items()
    }
    decision_input_sha256 = _canonical_digest(
        {
            "request": request.model_dump(mode="json"),
            "candidates": [
                {
                    "start": candidate["start"].isoformat(),
                    "end": candidate["end"].isoformat(),
                    "curtailed_mwh": candidate["curtailed_mwh"],
                    "period": candidate["period"],
                    "source_sha256": candidate["source_sha256"],
                    "method": candidate["method"],
                }
                for candidate in candidates
            ],
        }
    )

    def candidate_context(candidate: dict) -> str:
        return _json_context(
            "maintenance_rank",
            asset_id=request.asset_id,
            candidate_start=candidate["start"].isoformat(),
            candidate_end=candidate["end"].isoformat(),
            baseline_start=baseline.isoformat(),
            request_start=request.start.isoformat(),
            request_end=request.end.isoformat(),
            input_evidence_ids=input_evidence_ids,
            decision_input_sha256=decision_input_sha256,
        )

    def candidate_energy_provenance(candidate: dict) -> EvidenceProvenance:
        context = candidate_context(candidate)
        return _field_provenance(
            field_name="expected_curtailed_energy",
            method_version=candidate["method"],
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
        )

    baseline_energy_provenance = candidate_energy_provenance(baseline_candidate)
    ranked_windows = []
    for rank, candidate in enumerate(candidates, start=1):
        energy = candidate["curtailed_mwh"]
        opportunity_cost = _checked_multiply(energy, request.energy_price.value, "opportunity_cost")
        difference = _checked_subtract(energy, baseline_energy, "difference_from_baseline_mwh")
        context = candidate_context(candidate)
        energy_provenance = candidate_energy_provenance(candidate)
        cost_provenance = _field_provenance(
            field_name="opportunity_cost",
            method_version="opportunity_cost_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                request.energy_price.provenance.evidence_id,
            ],
        )
        difference_mwh_provenance = _field_provenance(
            field_name="difference_from_baseline_mwh",
            method_version="maintenance_difference_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"], baseline_candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                baseline_energy_provenance.evidence_id,
            ],
        )
        difference_provenance = _field_provenance(
            field_name="difference_from_baseline",
            method_version="maintenance_difference_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"], baseline_candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                baseline_energy_provenance.evidence_id,
            ],
        )
        rank_provenance = _field_provenance(
            field_name="rank",
            method_version="maintenance_rank_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        start_provenance = _field_provenance(
            field_name="start",
            method_version="maintenance_window_boundary_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        end_provenance = _field_provenance(
            field_name="end",
            method_version="maintenance_window_boundary_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        ranked_windows.append(
            RankedMaintenanceWindow(
                rank=rank,
                start=candidate["start"],
                end=candidate["end"],
                expected_curtailed_energy=NumericEvidence(
                    value=energy,
                    unit="MWh",
                    period=Period(
                        start=candidate["start"].date(),
                        end=candidate["end"].date(),
                    ),
                    source="ONS/restricao_coff_eolica_tm",
                    data_version=candidate["period"],
                    method=candidate["method"],
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    limitations=[limitation],
                    provenance_id=energy_provenance.evidence_id,
                    provenance=energy_provenance,
                ),
                opportunity_cost=MonetaryEvidence(
                    value=opportunity_cost,
                    unit="BRL",
                    source=request.energy_price.source,
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    provenance_id=cost_provenance.evidence_id,
                    provenance=cost_provenance,
                ),
                difference_from_baseline_mwh=difference,
                difference_from_baseline=NumericEvidence(
                    value=difference,
                    unit="MWh",
                    period=Period(
                        start=candidate["start"].date(),
                        end=candidate["end"].date(),
                    ),
                    source="ONS/restricao_coff_eolica_tm",
                    data_version=candidate["period"],
                    method="candidate minus baseline expected curtailed energy",
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    limitations=[limitation],
                    provenance_id=difference_provenance.evidence_id,
                    provenance=difference_provenance,
                ),
                field_provenance={
                    "rank": rank_provenance,
                    "start": start_provenance,
                    "end": end_provenance,
                    "expected_curtailed_energy": energy_provenance,
                    "opportunity_cost": cost_provenance,
                    "difference_from_baseline_mwh": difference_mwh_provenance,
                    "difference_from_baseline": difference_provenance,
                },
            )
        )

    response = MaintenanceRankResponse(
        asset_id=request.asset_id,
        ranking_mode="historical_prototype",
        data_mode="ons_materialized",
        baseline_window_start=baseline,
        input_provenance=input_provenance,
        ranked_windows=ranked_windows,
        limitations=[limitation],
    )
    _persist_operation(
        issued_provenance_repository,
        operation="maintenance_rank",
        request_value={
            "request": request.model_dump(mode="json"),
            "decision_input_sha256": decision_input_sha256,
        },
        provenances=[
            provenance
            for window in response.ranked_windows
            for provenance in window.field_provenance.values()
        ],
        source_records=[asset_item],
    )
    return response


def build_screen_bess(
    request: BessScreenRequest, repository: Any, issued_provenance_repository: Any
) -> BessScreenResponse:
    input_provenance = request.input_provenance or {}
    _validate_caller_provenance_impl(input_provenance, issued_provenance_repository)
    item = repository.get_asset(request.asset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    residual_exposure = _checked_float(item.get("curtailed_mwh"), "residual_exposure_mwh")
    if residual_exposure < 0:
        raise HTTPException(status_code=422, detail="Exposição residual não pode ser negativa.")
    annual_energy_capacity = _checked_multiply(
        _checked_multiply(request.energy_mwh, request.cycles_per_year, "annual_energy_capacity"),
        request.round_trip_efficiency,
        "annual_energy_capacity",
    )
    absorbable = min(residual_exposure, annual_energy_capacity)
    annual_benefit = _checked_multiply(
        absorbable, request.energy_price_brl_mwh, "annual_benefit_brl"
    )
    annual_net_benefit = _checked_subtract(
        annual_benefit, request.annualized_cost_brl, "annual_net_benefit_brl"
    )
    limitation = (
        "Triagem determinística sobre exposição histórica: não é dimensionamento, previsão "
        "de despacho ou garantia de corte evitado."
    )
    decision_input_sha256 = _canonical_digest(
        {
            "request": request.model_dump(mode="json"),
            "materialized_source": {
                "asset_id": item["asset_id"],
                "period": item["period"],
                "period_start": item["period_start"],
                "period_end": item["period_end"],
                "curtailed_mwh": residual_exposure,
                "source_key": item["source_key"],
                "source_sha256": item["source_sha256"],
                "method": item["method"],
            },
        }
    )
    source_observation = _field_provenance(
        field_name="residual_exposure_source",
        method_version="curtailed_energy_sum_v1",
        context=_json_context(
            "bess_screen_source",
            asset_id=request.asset_id,
            period=item["period"],
            decision_input_sha256=decision_input_sha256,
        ),
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=["Agregado mensal curado e calculado a partir de observações públicas."],
        source_hashes=[item["source_sha256"]],
        source_item=item,
        source_uri=f"curtailess://assets/{request.asset_id}/materialized-exposure",
    )
    output_parent_ids = sorted(
        {
            source_observation.evidence_id,
            *(provenance.evidence_id for provenance in input_provenance.values()),
        }
    )
    output_context = _json_context(
        "bess_screen",
        asset_id=request.asset_id,
        maintenance_result_id=request.maintenance_result_id,
        parent_evidence_ids=output_parent_ids,
        decision_input_sha256=decision_input_sha256,
        inputs={
            field_name: getattr(request, field_name)
            for field_name in (
                "power_mw",
                "energy_mwh",
                "capex_brl",
                "annualized_cost_brl",
                "round_trip_efficiency",
                "cycles_per_year",
                "energy_price_brl_mwh",
            )
        },
    )
    period = Period(
        start=date.fromisoformat(item["period_start"][:10]),
        end=date.fromisoformat(item["period_end"][:10]),
    )

    def simulation_provenance(field_name: str, method_version: str) -> EvidenceProvenance:
        return _field_provenance(
            field_name=field_name,
            method_version=method_version,
            context=output_context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri=f"curtailess://bess/{request.asset_id}/screen",
            parent_evidence_ids=output_parent_ids,
        )

    output_values = {
        "residual_exposure_mwh": round(residual_exposure, 6),
        "technically_absorbable_mwh": round(absorbable, 6),
        "annual_benefit_brl": round(annual_benefit, 2),
        "annual_net_benefit_brl": round(annual_net_benefit, 2),
        "preliminary_viable": float(annual_net_benefit > 0),
    }
    output_evidence: dict[str, NumericEvidence | MonetaryEvidence] = {}
    for field_name, value in output_values.items():
        provenance = simulation_provenance(field_name, "bess_screen_v1")
        if field_name.endswith("_brl"):
            output_evidence[field_name] = MonetaryEvidence(
                value=value,
                unit="BRL",
                source="historical exposure and client-informed BESS assumptions",
                value_status="calculado",
                origin=DataOrigin.PROXY_CALCULADO,
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            )
        else:
            output_evidence[field_name] = NumericEvidence(
                value=value,
                unit="boolean" if field_name == "preliminary_viable" else "MWh",
                period=period,
                source="historical exposure and client-informed BESS assumptions",
                data_version=item["period"],
                method="deterministic BESS screening",
                value_status="calculado",
                origin=DataOrigin.PROXY_CALCULADO,
                limitations=[limitation],
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            )
    response = BessScreenResponse(
        asset_id=request.asset_id,
        maintenance_result_id=request.maintenance_result_id,
        screening_mode="historical_deterministic",
        data_mode="ons_materialized",
        residual_exposure_mwh=round(residual_exposure, 6),
        technically_absorbable_mwh=round(absorbable, 6),
        annual_benefit_brl=round(annual_benefit, 2),
        annual_net_benefit_brl=round(annual_net_benefit, 2),
        preliminary_viable=annual_net_benefit > 0,
        input_provenance=input_provenance,
        source_observation=source_observation,
        output_evidence=output_evidence,
        missing_data=[
            "soc_cronológico",
            "degradação",
            "disponibilidade",
            "limite_de_conexão",
            "preço_horário",
            "fronteira_de_medição",
        ],
        limitations=[
            limitation,
            *(
                ["Proveniência de entradas legadas inferida como CLIENTE_INFORMADO."]
                if any(
                    provenance.method_version == "client_input_inferred_v1"
                    for provenance in input_provenance.values()
                )
                else []
            ),
        ],
    )
    _persist_operation(
        issued_provenance_repository,
        operation="bess_screen",
        request_value={
            "request": request.model_dump(mode="json"),
            "decision_input_sha256": decision_input_sha256,
        },
        provenances=[
            source_observation,
            *(evidence.provenance for evidence in response.output_evidence.values()),
        ],
        source_records=[item],
    )
    return response
