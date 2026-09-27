import math
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import HTTPException

from .canonical import canonical_json
from .provenance_service import aware
from .provenance_service import field_provenance as build_field_provenance
from .schemas import (
    MAX_PLANNING_RESULTS,
    Asset,
    DataOrigin,
    EvidenceProvenance,
    ExposureResponse,
    HistoricalWindow,
    HistoricalWindowsResponse,
    NumericEvidence,
    Period,
)


def _finite_float(value: Any, field_name: str) -> float:
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


def _optional_aware(item: dict[str, Any], key: str) -> datetime | None:
    value = item.get(key)
    return aware(value) if value else None


def materialized_asset(item: dict[str, Any]) -> Asset:
    asset_id = item["asset_id"]
    capacity = item.get("capacity_mw")
    if capacity is not None:
        capacity = _finite_float(capacity, "capacity_mw")
    common_limitations = ["Campo cadastral materializado de fonte pública do ONS."]
    field_provenance = {
        field_name: build_field_provenance(
            field_name=field_name,
            method_version="ons_materialized_asset_v1",
            context=asset_id,
            origin=DataOrigin.ONS_PUBLICO,
            limitations=common_limitations,
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri="s3://ons-aws-prod-opendata/dataset/restricao_coff_eolica_tm/",
        )
        for field_name in ("asset_id", "name", "technology", "ons_group", "connection_point")
    }
    capacity_provenance = None
    if capacity is not None:
        capacity_limitations = list(item.get("capacity_limitations", []))
        capacity_valid_from = _optional_aware(item, "capacity_valid_from")
        capacity_valid_to = _optional_aware(item, "capacity_valid_to")
        capacity_observed_at = _optional_aware(item, "capacity_observed_at")
        capacity_effective_at = _optional_aware(item, "capacity_effective_at")
        if not capacity_observed_at and not capacity_effective_at:
            capacity_limitations.append(
                "Metadados de validade temporal da fonte de capacidade indisponíveis; "
                "validade aberta/desconhecida."
            )
        if bool(capacity_valid_from) != bool(capacity_valid_to):
            capacity_limitations.append(
                "Intervalo temporal da capacidade incompleto; validade tratada como "
                "aberta/desconhecida."
            )
            capacity_valid_from = capacity_valid_to = None
        capacity_provenance = build_field_provenance(
            field_name="capacity_mw",
            method_version="ons_capacity_source_v1",
            context=asset_id,
            origin=DataOrigin.ONS_PUBLICO,
            limitations=capacity_limitations,
            source_hashes=[item["capacity_source_sha256"]],
            source_uri="s3://ons-aws-prod-opendata/dataset/capacidade-geracao/",
            source_key=item["capacity_source_key"],
            use_source_period=False,
            observed_at=capacity_observed_at,
            effective_at=capacity_effective_at,
            valid_from=capacity_valid_from,
            valid_to=capacity_valid_to,
        )
        field_provenance["capacity_mw"] = capacity_provenance
    else:
        field_provenance["capacity_mw"] = build_field_provenance(
            field_name="capacity_mw",
            method_version="asset_capacity_unavailable_v1",
            context=asset_id,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=["Capacidade não materializada para este ativo."],
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri=f"curtailess://assets/{asset_id}",
        )
    return Asset(
        asset_id=asset_id,
        name=item["asset_name"],
        technology="wind",
        capacity_mw=capacity,
        capacity_provenance=capacity_provenance,
        ons_group=asset_id,
        connection_point=item["point_id"],
        data_mode="ons_materialized",
        field_provenance=field_provenance,
    )


def build_exposure_response(
    asset_id: str,
    start: date,
    end: date,
    reason: Literal["ENE", "REL", "CNF"] | None,
    exposure: dict[str, Any],
) -> tuple[ExposureResponse, EvidenceProvenance]:
    if len(exposure["items"]) > MAX_PLANNING_RESULTS:
        raise HTTPException(
            status_code=422,
            detail=f"Exposição excede o limite de {MAX_PLANNING_RESULTS} períodos.",
        )
    total = _finite_float(exposure["curtailed_mwh"], "total_curtailed_energy")
    limitation = (
        "Agregado mensal materializado de dados públicos do ONS; períodos mensais "
        "sobrepostos são incluídos integralmente."
    )
    first_item = exposure["items"][0]
    provenance = build_field_provenance(
        field_name="total_curtailed_energy",
        method_version="curtailed_energy_sum_v1",
        context=f"{asset_id}:{start}:{end}:{reason or 'all'}",
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=exposure["source_sha256s"],
        source_item=first_item,
        source_items=exposure["items"],
        source_uri=f"curtailess://assets/{asset_id}/exposure",
        observed_at=max(aware(item["period_end"]) for item in exposure["items"]),
        valid_from=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        valid_to=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
    )
    response = ExposureResponse(
        asset_id=asset_id,
        perspective_type="historical_observed",
        data_mode="ons_materialized",
        granularity="period",
        reason=reason,
        technology="wind",
        total_curtailed_energy=NumericEvidence(
            value=total,
            unit="MWh",
            period=Period(start=start, end=end),
            source="ONS/restricao_coff_eolica_tm",
            data_version=",".join(exposure["periods"]),
            method=first_item["method"],
            value_status="calculado",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            provenance_id=provenance.evidence_id,
            provenance=provenance,
        ),
        limitations=[limitation],
    )
    return response, provenance


def build_historical_windows_response(
    asset_id: str,
    duration_hours: int,
    reason: Literal["ENE", "REL", "CNF"] | None,
    asset_item: dict[str, Any],
    materialized_windows: list[dict[str, Any]],
) -> HistoricalWindowsResponse:
    if len(materialized_windows) > MAX_PLANNING_RESULTS:
        raise HTTPException(
            status_code=422,
            detail=f"Resultado excede o limite de {MAX_PLANNING_RESULTS} janelas.",
        )
    limitation = (
        "Sinal derivado da taxa mensal histórica materializada; não é previsão "
        "operacional ex ante nem preserva a distribuição intramensal."
    )
    windows = []
    for window in materialized_windows:
        value = _finite_float(window.get("curtailed_mwh"), "expected_curtailed_energy")
        provenance = build_field_provenance(
            field_name="expected_curtailed_energy",
            method_version=window["method"],
            context=canonical_json(
                {
                    "kind": "historical_window",
                    "asset_id": asset_id,
                    "start": window["start"].isoformat(),
                    "end": window["end"].isoformat(),
                    "reason": reason,
                }
            ),
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[window["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://assets/{asset_id}/windows",
        )
        windows.append(
            HistoricalWindow(
                start=window["start"],
                end=window["end"],
                expected_curtailed_energy=NumericEvidence(
                    value=value,
                    unit="MWh",
                    period=Period(start=window["start"].date(), end=window["end"].date()),
                    source="ONS/restricao_coff_eolica_tm",
                    data_version=window["period"],
                    method=window["method"],
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    limitations=[limitation],
                    provenance_id=provenance.evidence_id,
                    provenance=provenance,
                ),
            )
        )
    return HistoricalWindowsResponse(
        asset_id=asset_id,
        perspective_type="historical_seasonal",
        validation_status="historical_signal",
        data_mode="ons_materialized",
        duration_hours=duration_hours,
        reason=reason,
        windows=windows,
        limitations=[limitation],
    )
