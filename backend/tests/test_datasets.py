from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from curtailess.datasets import DATASET_REGISTRY, DatasetPeriod, DatasetSpec, get_dataset_spec
from curtailess.schemas import (
    DataOrigin,
    EvidenceProvenance,
    MonetaryEvidence,
    NumericEvidence,
    Period,
    build_evidence_id,
    inferred_client_provenance,
    parse_evidence_id,
    validate_public_and_simulated_evidence,
)


def test_data_origin_values_are_the_approved_vocabulary() -> None:
    assert [origin.value for origin in DataOrigin] == [
        "ONS_PUBLICO",
        "PROXY_CALCULADO",
        "SIMULADO",
        "CLIENTE_INFORMADO",
    ]


def test_registry_contains_only_verified_planned_public_datasets() -> None:
    assert set(DATASET_REGISTRY) == {
        "restricao_coff_eolica_tm",
        "restricao_coff_fotovoltaica_tm",
        "programacao_x_previsao",
        "geracao_usina_2_ho",
        "usina_conjunto",
        "capacidade-geracao",
    }
    for dataset_id, spec in DATASET_REGISTRY.items():
        assert spec.dataset_id == dataset_id
        assert spec.s3_prefix == f"dataset/{dataset_id}/"
        assert spec.required_columns
        assert spec.aliases
        assert spec.source_timezone == "America/Sao_Paulo"
        assert spec.materializer
        assert spec.schema_version == "1"
        assert spec.enabled_modes


def test_unknown_dataset_is_rejected() -> None:
    with pytest.raises(ValueError, match="Dataset ONS não registrado"):
        get_dataset_spec("dataset_inventado")


def test_monthly_constrained_off_period_parsing_is_dataset_specific() -> None:
    wind = get_dataset_spec("restricao_coff_eolica_tm")
    solar = get_dataset_spec("restricao_coff_fotovoltaica_tm")

    assert wind.period_parser(
        "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"
    ) == DatasetPeriod(
        label="2026-09",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        granularity="month",
    )
    assert (
        solar.period_parser(
            "dataset/restricao_coff_fotovoltaica_tm/RESTRICAO_COFF_FOTOVOLTAICA_2024_04.parquet"
        ).label
        == "2024-04"
    )
    with pytest.raises(ValueError, match="não corresponde ao padrão"):
        wind.period_parser("RESTRICAO_COFF_FOTOVOLTAICA_2026_09.parquet")


def test_daily_and_yearly_period_parsing_matches_verified_ons_names() -> None:
    forecast = get_dataset_spec("programacao_x_previsao").period_parser(
        "dataset/programacao_x_previsao/PROGRAMACAO_X_PREVISAO_2024_10_01.parquet"
    )
    generation = get_dataset_spec("geracao_usina_2_ho").period_parser(
        "dataset/geracao_usina_2_ho/GERACAO_USINA-2_2021.parquet"
    )

    assert forecast == DatasetPeriod(
        label="2024-10-01",
        start=date(2024, 10, 1),
        end=date(2024, 10, 1),
        granularity="day",
    )
    assert generation == DatasetPeriod(
        label="2021",
        start=date(2021, 1, 1),
        end=date(2021, 12, 31),
        granularity="year",
    )


def test_generation_period_parser_supports_verified_monthly_files_since_2022() -> None:
    generation = get_dataset_spec("geracao_usina_2_ho").period_parser(
        "dataset/geracao_usina_2_ho/GERACAO_USINA-2_2026_09.parquet"
    )

    assert generation == DatasetPeriod(
        label="2026-09",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        granularity="month",
    )


def test_generation_period_parser_rejects_unverified_granularity_for_year() -> None:
    parser = get_dataset_spec("geracao_usina_2_ho").period_parser

    with pytest.raises(ValueError, match="até 2021"):
        parser("GERACAO_USINA-2_2025.parquet")
    with pytest.raises(ValueError, match="desde 2022"):
        parser("GERACAO_USINA-2_2021_09.parquet")


def test_capacity_identity_uses_verified_ceg_not_absent_id_ons_column() -> None:
    capacity = get_dataset_spec("capacidade-geracao")

    assert "id_ons" not in capacity.required_columns
    assert capacity.aliases["asset_external_id"] == ("ceg",)


def test_unversioned_identity_files_are_explicit_snapshots() -> None:
    relationship = get_dataset_spec("usina_conjunto").period_parser(
        "dataset/usina_conjunto/RELACIONAMENTO_USINA_CONJUNTO.parquet"
    )
    capacity = get_dataset_spec("capacidade-geracao").period_parser(
        "dataset/capacidade-geracao/CAPACIDADE_GERACAO.parquet"
    )

    assert relationship == DatasetPeriod(
        label="snapshot",
        start=None,
        end=None,
        granularity="snapshot",
    )
    assert capacity == relationship
    assert get_dataset_spec("usina_conjunto").enabled_modes == frozenset({"incremental"})


def test_dataset_spec_is_strict_and_forbids_unknown_metadata() -> None:
    payload = {
        **get_dataset_spec("restricao_coff_eolica_tm").model_dump(),
        "unsupported_filename_guess": "RESTRICAO_*.parquet",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DatasetSpec.model_validate(payload)


def public_evidence() -> EvidenceProvenance:
    return EvidenceProvenance(
        evidence_id="ons:restricao:2026-09:abc",
        field_name="curtailed_mwh",
        origin=DataOrigin.ONS_PUBLICO,
        source_key=("dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"),
        source_sha256="a" * 64,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        effective_at=None,
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
        valid_to=datetime(2026, 10, 1, tzinfo=UTC),
        method_version="ons_source_v1",
        limitations=[],
    )


def test_evidence_provenance_requires_origin_source_and_method_metadata() -> None:
    evidence = public_evidence()

    assert evidence.origin is DataOrigin.ONS_PUBLICO
    assert evidence.source_uri is None
    with pytest.raises(ValidationError):
        EvidenceProvenance.model_validate(
            {
                "evidence_id": "missing-contracts",
                "limitations": [],
            }
        )
    with pytest.raises(ValidationError, match="source_uri ou source_key"):
        EvidenceProvenance(
            evidence_id="no-source",
            field_name="test_field",
            origin=DataOrigin.ONS_PUBLICO,
            method_version="ons_source_v1",
            limitations=[],
        )


def test_evidence_provenance_rejects_bad_hash_naive_timestamps_and_invalid_interval() -> None:
    payload = public_evidence().model_dump()
    payload["source_sha256"] = "not-a-sha256"
    with pytest.raises(ValidationError):
        EvidenceProvenance.model_validate(payload)

    payload = public_evidence().model_dump()
    payload["observed_at"] = datetime(2026, 9, 1)
    with pytest.raises(ValidationError, match="timezone"):
        EvidenceProvenance.model_validate(payload)

    payload = public_evidence().model_dump()
    payload["valid_to"] = datetime(2026, 8, 31, tzinfo=UTC)
    with pytest.raises(ValidationError, match="valid_to"):
        EvidenceProvenance.model_validate(payload)


def test_parent_lineage_is_structured_unique_and_deterministic() -> None:
    inferred = inferred_client_provenance("duration_hours", 72, "maintenance:asset-1")
    repeated = inferred_client_provenance("duration_hours", 72, "maintenance:asset-1")

    assert inferred == repeated
    assert inferred.origin is DataOrigin.CLIENTE_INFORMADO
    assert "inferida" in " ".join(inferred.limitations).lower()
    with pytest.raises(ValidationError, match="sorted and unique"):
        EvidenceProvenance.model_validate(
            {
                **public_evidence().model_dump(),
                "parent_evidence_ids": ["parent-b", "parent-a", "parent-a"],
            }
        )


def test_public_observation_and_simulation_require_distinct_ids_and_origins() -> None:
    public = public_evidence()
    simulated = EvidenceProvenance(
        evidence_id="simulation:plant-state:v1:def",
        field_name="plant_state",
        origin=DataOrigin.SIMULADO,
        source_uri="curtailess://plant-state/CJU_TESTE/2026-09-01T00:00:00Z",
        source_sha256=None,
        observed_at=None,
        effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        valid_from=None,
        valid_to=None,
        method_version="plant_state_v1",
        limitations=["Estado atual estimado; não é SCADA privado."],
    )

    validate_public_and_simulated_evidence(public, simulated)

    with pytest.raises(ValueError, match="evidence_id"):
        validate_public_and_simulated_evidence(
            public,
            simulated.model_copy(update={"evidence_id": public.evidence_id}),
        )
    with pytest.raises(ValueError, match="SIMULADO"):
        validate_public_and_simulated_evidence(
            public,
            simulated.model_copy(update={"origin": DataOrigin.ONS_PUBLICO}),
        )


@pytest.mark.parametrize(
    ("value_status", "origin"),
    [
        ("medido", DataOrigin.ONS_PUBLICO),
        ("previsto", DataOrigin.ONS_PUBLICO),
        ("calculado", DataOrigin.PROXY_CALCULADO),
        ("simulado", DataOrigin.SIMULADO),
        ("informado", DataOrigin.CLIENTE_INFORMADO),
    ],
)
def test_numeric_evidence_enforces_status_origin_mapping(value_status, origin) -> None:
    provenance = public_evidence().model_copy(update={"origin": origin})
    evidence = NumericEvidence(
        value=1.0,
        unit="MWh",
        period=Period(start=date(2026, 9, 1), end=date(2026, 9, 1)),
        source="test",
        data_version="v1",
        method="test_method",
        value_status=value_status,
        origin=origin,
        limitations=[],
        provenance_id=provenance.evidence_id,
        provenance=provenance,
    )
    assert evidence.origin is origin


def test_evidence_models_reject_missing_or_contradictory_origin_and_provenance() -> None:
    provenance = public_evidence()
    base = {
        "value": 1.0,
        "unit": "MWh",
        "period": Period(start=date(2026, 9, 1), end=date(2026, 9, 1)),
        "source": "test",
        "data_version": "v1",
        "method": "test_method",
        "value_status": "medido",
        "limitations": [],
        "provenance_id": provenance.evidence_id,
        "provenance": provenance,
    }
    with pytest.raises(ValidationError):
        NumericEvidence.model_validate(base)
    with pytest.raises(ValidationError, match="origin"):
        NumericEvidence.model_validate({**base, "origin": DataOrigin.SIMULADO})
    with pytest.raises(ValidationError, match="provenance"):
        NumericEvidence.model_validate(
            {**base, "origin": DataOrigin.ONS_PUBLICO, "provenance_id": "different"}
        )

    with pytest.raises(ValidationError, match="origin"):
        MonetaryEvidence(
            value=10,
            unit="BRL",
            source="test",
            value_status="simulado",
            origin=DataOrigin.PROXY_CALCULADO,
            provenance_id=provenance.evidence_id,
            provenance=provenance,
        )


def test_field_level_evidence_ids_are_unique_self_describing_and_tamper_evident() -> None:
    source_hashes = ["a" * 64, "b" * 64]
    count_id = build_evidence_id(source_hashes, "entity_count", "point_context_v1", "point-1")
    rate_id = build_evidence_id(
        source_hashes,
        "simultaneity_rate",
        "historical_simultaneity_v1",
        "point-1",
    )

    assert count_id != rate_id
    assert "," not in count_id
    assert parse_evidence_id(count_id) == {
        "context": "point-1",
        "field": "entity_count",
        "method": "point_context_v1",
        "sources": source_hashes,
    }
    with pytest.raises(ValueError, match="inválido"):
        parse_evidence_id(count_id[:-1] + "0")
