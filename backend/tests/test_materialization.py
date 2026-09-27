import hashlib
import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import duckdb
import pytest

from curtailess.ingestion_state import ClaimResult
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
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls = []

    def download_file(self, bucket, key, filename):
        assert bucket == "data-bucket"
        assert key.endswith(".parquet")
        shutil.copyfile(self.source_path, filename)

    def put_object(self, **kwargs):
        object_id = (kwargs["Bucket"], kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and object_id in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        self.put_calls.append(kwargs)
        self.objects[object_id] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}


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


class FakeLedger:
    def __init__(self, item):
        self.item = deepcopy(item)
        self.claims = []
        self.completed = []
        self.failed = []
        self.outcome = "CLAIMED"

    def claim_materialization(self, fingerprint, **kwargs):
        self.claims.append({"fingerprint": fingerprint, **kwargs})
        return ClaimResult(self.outcome, deepcopy(self.item))

    def get(self, fingerprint):
        assert fingerprint == self.item["source_fingerprint"]
        return deepcopy(self.item)

    def mark_materialized(self, fingerprint, **kwargs):
        self.completed.append({"fingerprint": fingerprint, **kwargs})
        return {"state": "MATERIALIZED"}

    def mark_materialization_failed(self, fingerprint, **kwargs):
        self.failed.append({"fingerprint": fingerprint, **kwargs})
        return {"state": "FAILED"}


def materialization_message(path: Path) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint = "a" * 64
    dataset = "restricao_coff_eolica_tm"
    return {
        "bucket": "data-bucket",
        "dataset": dataset,
        "source_period": "2026-08",
        "source_fingerprint": fingerprint,
        "raw_key": (
            f"raw/ons/{dataset}/source_year=2026/source_month=08/"
            f"sha256={digest[:2]}/{digest}.parquet"
        ),
        "raw_sha256": digest,
        "manifest_key": f"manifests/{dataset}/source_fingerprint={fingerprint}.json",
    }


def ledger_item(message: dict) -> dict:
    return {
        **message,
        "source_bucket": "ons-aws-prod-opendata",
        "source_key": ("dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_08.parquet"),
        "source_etag": "source-etag",
        "source_size": 123,
        "source_last_modified": "2026-09-03T00:00:00+00:00",
    }


def test_materialization_handler_validates_persists_and_finalizes_manifest(
    ons_parquet: Path,
) -> None:
    s3 = FakeS3(ons_parquet)
    table = FakeTable()
    message = materialization_message(ons_parquet)
    ledger = FakeLedger(ledger_item(message))
    result = materialization_handler(
        {"Records": [{"messageId": "materialize-1", "body": json.dumps(message)}]},
        None,
        s3_client=s3,
        table=table,
        ledger=ledger,
        environment={"DATA_BUCKET": "data-bucket", "INGESTION_LEASE_SECONDS": "300"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
    )
    assert result == {"batchItemFailures": []}
    assert len(table.items) == 2
    top = max(table.items, key=lambda item: item["curtailed_mwh"])
    assert top["asset_id"] == "CJU_RSSVPA"
    assert top["curtailed_mwh"] == 15
    assert top["data_mode"] == "ons_materialized"
    assert top["source_sha256"] == message["raw_sha256"]
    assert top["source_fingerprint"] == message["source_fingerprint"]

    summary_key = "curated/settlement_energy/period=2026-08/summary.json"
    summary = json.loads(s3.objects[("data-bucket", summary_key)])
    assert summary["row_count"] == 3
    assert summary["asset_count"] == 2
    manifest = json.loads(s3.objects[("data-bucket", message["manifest_key"])])
    assert manifest["raw"]["sha256"] == message["raw_sha256"]
    assert manifest["source"]["etag"] == "source-etag"
    assert ledger.completed[0]["manifest_key"] == message["manifest_key"]
    assert ledger.failed == []
    assert s3.put_calls[-1]["IfNoneMatch"] == "*"


def test_materialization_retry_reuses_identical_immutable_manifest(ons_parquet: Path) -> None:
    s3 = FakeS3(ons_parquet)
    table = FakeTable()
    message = materialization_message(ons_parquet)
    first_ledger = FakeLedger(ledger_item(message))
    event = {"Records": [{"messageId": "first", "body": json.dumps(message)}]}
    assert materialization_handler(
        event,
        None,
        s3_client=s3,
        table=table,
        ledger=first_ledger,
        environment={"DATA_BUCKET": "data-bucket"},
    ) == {"batchItemFailures": []}

    retry_ledger = FakeLedger(ledger_item(message))
    retry = materialization_handler(
        {"Records": [{"messageId": "retry", "body": json.dumps(message)}]},
        None,
        s3_client=s3,
        table=table,
        ledger=retry_ledger,
        environment={"DATA_BUCKET": "data-bucket"},
    )
    assert retry == {"batchItemFailures": []}
    assert retry_ledger.completed
    manifest_writes = [call for call in s3.put_calls if call["Key"] == message["manifest_key"]]
    assert len(manifest_writes) == 1


def test_materialization_batch_reports_only_failed_record(ons_parquet: Path) -> None:
    s3 = FakeS3(ons_parquet)
    table = FakeTable()
    message = materialization_message(ons_parquet)
    invalid = {**message, "raw_sha256": "0" * 64}
    ledger = FakeLedger(ledger_item(message))
    result = materialization_handler(
        {
            "Records": [
                {"messageId": "valid", "body": json.dumps(message)},
                {"messageId": "invalid", "body": json.dumps(invalid)},
            ]
        },
        None,
        s3_client=s3,
        table=table,
        ledger=ledger,
        environment={"DATA_BUCKET": "data-bucket"},
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "invalid"}]}
