from pathlib import Path

import duckdb
import pytest

from curtailess.datasets import get_dataset_spec
from curtailess.materializers import MaterializationContext, resolve_materializer


def context(tmp_path: Path, dataset: str, period: str) -> MaterializationContext:
    return MaterializationContext(
        spec=get_dataset_spec(dataset),
        period=period,
        source_path=tmp_path / "source.parquet",
        curated_path=tmp_path / f"{dataset}.parquet",
        source_fingerprint="a" * 64,
        source_sha256="b" * 64,
        source_bucket="ons-aws-prod-opendata",
        source_key=f"dataset/{dataset}/source.parquet",
        source_last_modified="2026-09-27T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("dataset", "technology"),
    [
        ("restricao_coff_eolica_tm", "wind"),
        ("restricao_coff_fotovoltaica_tm", "solar"),
    ],
)
def test_constrained_off_preserves_par_null_unknown_and_quality_counts(
    tmp_path: Path, dataset: str, technology: str
) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
                id_ons VARCHAR, nom_usina VARCHAR, id_estado VARCHAR,
                din_instante TIMESTAMP, val_geracao DOUBLE,
                val_disponibilidade DOUBLE, val_geracaolimitada DOUBLE,
                val_geracaoreferencia DOUBLE,
                val_geracaonaorealizadaapurada DOUBLE,
                cod_razaorestricao VARCHAR, cod_origemrestricao VARCHAR,
                id_pontoconexao VARCHAR, nom_pontoconexao VARCHAR, ceg VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "A",
                    "Ativo",
                    "RN",
                    "2026-09-01 00:00:00",
                    10,
                    20,
                    8,
                    12,
                    2,
                    "PAR",
                    "LOC",
                    "P",
                    "Ponto",
                    "-",
                ),
                (
                    "A",
                    "Ativo",
                    "RN",
                    "2026-09-01 00:30:00",
                    9,
                    20,
                    7,
                    11,
                    2,
                    None,
                    None,
                    "P",
                    "Ponto",
                    "-",
                ),
                (
                    "A",
                    "Ativo",
                    "RN",
                    "2026-09-01 01:00:00",
                    8,
                    None,
                    6,
                    10,
                    2,
                    "NOVO",
                    "SIS",
                    "P",
                    "Ponto",
                    "-",
                ),
                (
                    "A",
                    "Ativo",
                    "RN",
                    "2026-09-01 01:00:00",
                    8,
                    None,
                    6,
                    10,
                    2,
                    "NOVO",
                    "SIS",
                    "P",
                    "Ponto",
                    "-",
                ),
            ],
        )
        output = resolve_materializer("constrained_off")(
            connection, context(tmp_path, dataset, "2026-09")
        )
    item = output.dynamodb_items[0]
    assert item["technology"] == technology
    assert item["curtailed_mwh_by_reason"]["PAR"] == 1
    assert item["curtailed_mwh_by_reason"]["NC"] == 1
    assert item["curtailed_mwh_by_reason_exact"]["NOVO"]["curtailed_mwh"] == 2
    assert item["limited_interval_count_by_origin"]["__NULL__"] == 1
    assert item["duplicate_interval_count"] == 1
    assert item["null_counts"]["val_disponibilidade"] == 2
    assert output.metrics["unknown_reason_interval_count"] == 2
    assert context(tmp_path, dataset, "2026-09").curated_path.exists()


def test_forecast_materializer_types_values_and_derives_valid_instants(tmp_path: Path) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
                dat_programacao VARCHAR, num_patamar INTEGER,
                cod_usinapdp VARCHAR, nom_usinapdp VARCHAR,
                val_previsao VARCHAR, val_programado VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("20260927", 1, "SOL  ", "Solar  ", "1,5", "2.0"),
                ("20260927", 2, "SOL  ", "Solar  ", "3.0", "4.0"),
            ],
        )
        output = resolve_materializer("forecast")(
            connection, context(tmp_path, "programacao_x_previsao", "2026-09-27")
        )
    item = output.dynamodb_items[0]
    assert item["asset_id"] == "program:SOL"
    assert item["publication_time_status"] == "source_object_last_modified_proxy"
    assert item["intervals"][0]["valid_at"] == "2026-09-27T00:00:00-03:00"
    assert item["intervals"][1]["valid_at"] == "2026-09-27T00:30:00-03:00"
    assert item["intervals"][0]["forecast_mw"] == pytest.approx(1.5)


def test_generation_materializer_builds_hourly_and_seasonal_profiles(tmp_path: Path) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
                din_instante TIMESTAMP, id_ons VARCHAR, nom_usina VARCHAR,
                nom_tipousina VARCHAR, val_geracao DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?)",
            [
                ("2026-09-01 00:00:00", "A", "Ativo", "EOLIELÉTRICA", 10),
                ("2026-09-01 01:00:00", "A", "Ativo", "EOLIELÉTRICA", 20),
                ("2026-09-01 01:00:00", None, "Sem ID", "MMGD", 5),
            ],
        )
        output = resolve_materializer("generation")(
            connection, context(tmp_path, "geracao_usina_2_ho", "2026-09")
        )
    item = output.dynamodb_items[0]
    assert item["season"] == "spring"
    assert item["observed_generation_mwh"] == 30
    assert item["hour_of_day_profile"]["00"]["mean_mw"] == 10
    assert item["hour_of_day_profile"]["01"]["mean_mw"] == 20
    assert output.metrics["rows_without_asset_id"] == 1


def test_asset_relationship_materializer_keeps_effective_dates(tmp_path: Path) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
                id_ons_conjunto VARCHAR, id_ons_usina VARCHAR,
                nom_conjunto VARCHAR, nom_usina VARCHAR, ceg VARCHAR,
                dat_iniciorelacionamento VARCHAR, dat_fimrelacionamento VARCHAR,
                nom_tipousina VARCHAR, estad_id VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO source_rows VALUES "
            "('G', 'A', 'Grupo', 'Ativo', 'CEG', '2020-01-01', NULL, 'Solar', 'RN')"
        )
        output = resolve_materializer("assets")(
            connection, context(tmp_path, "usina_conjunto", "snapshot")
        )
    item = output.dynamodb_items[0]
    assert item["asset_id"] == "A"
    assert item["ons_group_id"] == "G"
    assert item["valid_from"] == "2020-01-01"
    assert item["valid_to"] is None


def test_capacity_materializer_aggregates_units_by_ceg(tmp_path: Path) -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
                ceg VARCHAR, nom_usina VARCHAR, nom_tipousina VARCHAR,
                cod_equipamento VARCHAR, dat_entradateste VARCHAR,
                dat_entradaoperacao VARCHAR, dat_desativacao VARCHAR,
                val_potenciaefetiva DOUBLE, id_estado VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("CEG", "Ativo", "Solar", "UG1", None, "2020-01-01", None, 10, "RN"),
                ("CEG", "Ativo", "Solar", "UG2", None, "2020-01-02", "2025-01-01", 20, "RN"),
            ],
        )
        output = resolve_materializer("assets")(
            connection, context(tmp_path, "capacidade-geracao", "snapshot")
        )
    item = output.dynamodb_items[0]
    assert item["asset_id"] == "ceg:CEG"
    assert item["total_capacity_mw"] == 30
    assert item["active_capacity_mw"] == 10
    assert item["capacity_as_of"] == "2026-09-27"
    assert item["distinct_equipment_count"] == 2
