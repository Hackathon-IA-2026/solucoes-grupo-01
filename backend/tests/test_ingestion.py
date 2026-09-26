import json
from datetime import UTC, datetime

from curtailess.ingestion import copy_handler, discover_latest_parquet, discovery_handler


class FakePaginator:
    def paginate(self, **kwargs):
        assert kwargs == {
            "Bucket": "ons-aws-prod-opendata",
            "Prefix": "dataset/restricao_coff_eolica_tm/",
        }
        return [
            {
                "Contents": [
                    {
                        "Key": "dataset/restricao_coff_eolica_tm/readme.pdf",
                        "Size": 100,
                        "ETag": '"pdf"',
                        "LastModified": datetime(2026, 9, 1, tzinfo=UTC),
                    },
                    {
                        "Key": "dataset/restricao_coff_eolica_tm/old.parquet",
                        "Size": 200,
                        "ETag": '"old"',
                        "LastModified": datetime(2026, 8, 1, tzinfo=UTC),
                    },
                    {
                        "Key": "dataset/restricao_coff_eolica_tm/latest.parquet",
                        "Size": 300,
                        "ETag": '"latest"',
                        "LastModified": datetime(2026, 9, 2, tzinfo=UTC),
                    },
                ]
            }
        ]


class FakeS3:
    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return FakePaginator()


def test_discover_latest_parquet_ignores_non_parquet_and_chooses_latest() -> None:
    discovered = discover_latest_parquet(
        FakeS3(),
        source_bucket="ons-aws-prod-opendata",
        source_prefix="dataset/restricao_coff_eolica_tm/",
    )

    assert discovered == {
        "key": "dataset/restricao_coff_eolica_tm/latest.parquet",
        "size": 300,
        "etag": "latest",
        "last_modified": "2026-09-02T00:00:00+00:00",
    }


class FakeSQS:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "message-1"}


def test_discovery_handler_enqueues_latest_source_object() -> None:
    sqs = FakeSQS()

    result = discovery_handler(
        {},
        None,
        s3_client=FakeS3(),
        sqs_client=sqs,
        environment={
            "SOURCE_BUCKET": "ons-aws-prod-opendata",
            "SOURCE_PREFIX": "dataset/restricao_coff_eolica_tm/",
            "SOURCE_DATASET": "restricao_coff_eolica_tm",
            "INGESTION_QUEUE_URL": "https://sqs.example/ingestion",
        },
    )

    assert result == {
        "dataset": "restricao_coff_eolica_tm",
        "source_key": "dataset/restricao_coff_eolica_tm/latest.parquet",
        "message_id": "message-1",
    }
    assert sqs.messages[0]["QueueUrl"] == "https://sqs.example/ingestion"
    body = json.loads(sqs.messages[0]["MessageBody"])
    assert body["source_bucket"] == "ons-aws-prod-opendata"
    assert body["source_key"].endswith("latest.parquet")
    assert body["dataset"] == "restricao_coff_eolica_tm"


class StreamingBody:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_chunks(self, chunk_size):
        assert chunk_size > 0
        yield from self.chunks


class FakeDestinationS3:
    def __init__(self):
        self.uploads = []
        self.objects = []

    def get_object(self, **kwargs):
        assert kwargs == {
            "Bucket": "ons-aws-prod-opendata",
            "Key": "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet",
        }
        return {"Body": StreamingBody([b"parquet-", b"bytes"])}

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "body": fileobj.read(),
                "extra_args": ExtraArgs,
            }
        )

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def test_copy_handler_preserves_raw_object_and_writes_traceable_manifest() -> None:
    s3 = FakeDestinationS3()
    event = {
        "Records": [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "dataset": "restricao_coff_eolica_tm",
                        "source_bucket": "ons-aws-prod-opendata",
                        "source_key": (
                            "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"
                        ),
                        "source_size": 13,
                        "source_etag": "source-etag",
                        "source_last_modified": "2026-09-03T00:00:00+00:00",
                    }
                ),
            }
        ]
    }

    result = copy_handler(
        event,
        None,
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 26, 18, 30, tzinfo=UTC),
    )

    assert result == {"batchItemFailures": []}
    assert s3.uploads[0]["key"] == (
        "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/"
        "RESTRICAO_COFF_EOLICA_2026_09.parquet"
    )
    assert s3.uploads[0]["body"] == b"parquet-bytes"
    assert s3.uploads[0]["extra_args"]["Metadata"]["source-etag"] == "source-etag"
    manifest_write = s3.objects[0]
    assert manifest_write["Key"] == (
        "manifests/restricao_coff_eolica_tm/ingestion_date=2026-09-26/"
        "RESTRICAO_COFF_EOLICA_2026_09.json"
    )
    manifest = json.loads(manifest_write["Body"])
    assert manifest["source_url"].startswith("s3://ons-aws-prod-opendata/")
    assert manifest["sha256"] == (
        "fba56374a33fa9ac89f203b90e6c34687cbd6721bfa94e78af45580a132641e0"
    )
    assert manifest["validation_status"] == "pending"


def test_copy_handler_starts_materialization_with_provenance() -> None:
    s3 = FakeDestinationS3()
    lambda_client = FakeLambda()
    event = {
        "Records": [
            {
                "messageId": "message-2",
                "body": json.dumps(
                    {
                        "dataset": "restricao_coff_eolica_tm",
                        "source_bucket": "ons-aws-prod-opendata",
                        "source_key": (
                            "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"
                        ),
                        "source_size": 13,
                        "source_etag": "source-etag",
                        "source_last_modified": "2026-09-03T00:00:00+00:00",
                    }
                ),
            }
        ]
    }
    result = copy_handler(
        event,
        None,
        s3_client=s3,
        lambda_client=lambda_client,
        environment={
            "DATA_BUCKET": "curtailess-data",
            "MATERIALIZATION_FUNCTION": "materialize-function",
        },
        now=lambda: datetime(2026, 9, 26, 18, 30, tzinfo=UTC),
    )
    assert result == {"batchItemFailures": []}
    call = lambda_client.calls[0]
    assert call["FunctionName"] == "materialize-function"
    assert call["InvocationType"] == "Event"
    payload = json.loads(call["Payload"])
    assert payload["bucket"] == "curtailess-data"
    assert payload["key"].startswith("raw/ons/")
    assert len(payload["sha256"]) == 64
