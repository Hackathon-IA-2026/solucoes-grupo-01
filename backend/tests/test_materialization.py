import json
import shutil
from pathlib import Path

import duckdb
import pytest

from curtailess.materialization import aggregate_exposure_rows, materialization_handler


def test_aggregate_exposure_rows_uses_apurada_only_when_limited() -> None:
    rows = [
        {
            "id_ons": "CJU_TESTE",
            "nom_usina": "Conjunto Teste",
            "id_pontoconexao": "PONTO_1",
            "nom_pontoconexao": "Ponto Um",
            "id_estado": "RN",
            "din_instante": "2026-08-01T00:00:00",
            "val_geracaolimitada": 80.0,
            "val_geracaonaorealizadaapurada": 20.0,
            "cod_razaorestricao": "CNF",
        },
        {
            "id_ons": "CJU_TESTE",
            "nom_usina": "Conjunto Teste",
            "id_pontoconexao": "PONTO_1",
            "nom_pontoconexao": "Ponto Um",
            "id_estado": "RN",
            "din_instante": "2026-08-01T00:30:00",
            "val_geracaolimitada": None,
            "val_geracaonaorealizadaapurada": 50.0,
            "cod_razaorestricao": "REL",
        },
        {
            "id_ons": "CJU_TESTE",
            "nom_usina": "Conjunto Teste",
            "id_pontoconexao": "PONTO_1",
            "nom_pontoconexao": "Ponto Um",
            "id_estado": "RN",
            "din_instante": "2026-08-01T01:00:00",
            "val_geracaolimitada": 70.0,
            "val_geracaonaorealizadaapurada": None,
            "cod_razaorestricao": None,
        },
    ]

    result = aggregate_exposure_rows(rows)

    assert result == [
        {
            "asset_id": "CJU_TESTE",
            "asset_name": "Conjunto Teste",
            "point_id": "PONTO_1",
            "point_name": "Ponto Um",
            "state": "RN",
            "period_start": "2026-08-01T00:00:00",
            "period_end": "2026-08-01T01:00:00",
            "interval_count": 3,
            "limited_interval_count": 2,
            "curtailed_mwh": 10.0,
            "curtailed_mwh_by_reason": {"CNF": 10.0, "REL": 0.0, "ENE": 0.0, "NC": 0.0},
            "value_status": "measured_ons",
            "method": "sum(apurada * 0.5) when val_geracaolimitada is not null",
        }
    ]


@pytest.fixture
def ons_parquet(tmp_path: Path) -> Path:
    path = tmp_path / "curtailess-ons-2026-08.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE ons_fixture (
                id_ons VARCHAR,
                nom_usina VARCHAR,
                id_pontoconexao VARCHAR,
                nom_pontoconexao VARCHAR,
                id_estado VARCHAR,
                din_instante TIMESTAMP,
                val_geracaolimitada DOUBLE,
                val_geracaonaorealizadaapurada DOUBLE,
                cod_razaorestricao VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO ons_fixture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "CJU_RSSVPA",
                    "Conjunto Serra Verde",
                    "PONTO_1",
                    "Ponto Um",
                    "RN",
                    "2026-08-01T00:00:00",
                    80.0,
                    20.0,
                    "CNF",
                ),
                (
                    "CJU_RSSVPA",
                    "Conjunto Serra Verde",
                    "PONTO_1",
                    "Ponto Um",
                    "RN",
                    "2026-08-01T00:30:00",
                    70.0,
                    10.0,
                    "REL",
                ),
                (
                    "CJU_TESTE",
                    "Conjunto Teste",
                    "PONTO_2",
                    "Ponto Dois",
                    "BA",
                    "2026-08-01T00:00:00",
                    None,
                    50.0,
                    None,
                ),
            ],
        )
        connection.execute("COPY ons_fixture TO ? (FORMAT PARQUET)", [str(path)])
    return path


class FakeS3:
    def __init__(self, source_path: Path):
        self.source_path = source_path

    def download_file(self, bucket, key, filename):
        assert bucket == "data-bucket"
        assert key.endswith("RESTRICAO_COFF_EOLICA_2026_08.parquet")
        shutil.copyfile(self.source_path, filename)

    def put_object(self, **kwargs):
        self.curated = kwargs


class FakeTable:
    def __init__(self):
        self.items = []

    class Batch:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            return self

        def put_item(self, *, Item):
            self.owner.items.append(Item)

        def __exit__(self, *args):
            return False

    def batch_writer(self):
        return self.Batch(self)


def test_materialization_handler_validates_and_persists_month(ons_parquet: Path) -> None:
    s3 = FakeS3(ons_parquet)
    table = FakeTable()
    result = materialization_handler(
        {
            "bucket": "data-bucket",
            "key": (
                "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=08/"
                "RESTRICAO_COFF_EOLICA_2026_08.parquet"
            ),
            "sha256": "source-sha256",
        },
        None,
        s3_client=s3,
        table=table,
    )
    assert result["validation_status"] == "valid"
    assert result["row_count"] == 3
    assert result["asset_count"] == 2
    assert len(table.items) == 2
    top = max(table.items, key=lambda item: item["curtailed_mwh"])
    assert top["asset_id"] == "CJU_RSSVPA"
    assert top["curtailed_mwh"] == 15
    assert top["data_mode"] == "ons_materialized"
    assert top["source_sha256"] == "source-sha256"
    curated = json.loads(s3.curated["Body"])
    assert curated["row_count"] == 3
    assert curated["asset_count"] == 2
