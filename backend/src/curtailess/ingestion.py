import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import boto3


def discover_latest_parquet(
    s3_client: Any,
    *,
    source_bucket: str,
    source_prefix: str,
) -> dict[str, object]:
    latest: dict[str, Any] | None = None
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=source_bucket, Prefix=source_prefix):
        for item in page.get("Contents", []):
            if not item["Key"].lower().endswith(".parquet"):
                continue
            if latest is None or item["LastModified"] > latest["LastModified"]:
                latest = item

    if latest is None:
        raise RuntimeError(f"Nenhum Parquet encontrado em s3://{source_bucket}/{source_prefix}")

    return {
        "key": latest["Key"],
        "size": latest["Size"],
        "etag": latest["ETag"].strip('"'),
        "last_modified": latest["LastModified"].isoformat(),
    }


def discovery_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    sqs_client: Any | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    del event, context
    environment = environment or os.environ
    s3_client = s3_client or boto3.client("s3", region_name="us-west-2")
    sqs_client = sqs_client or boto3.client("sqs", region_name="us-west-2")

    source_bucket = environment["SOURCE_BUCKET"]
    source_prefix = environment["SOURCE_PREFIX"]
    dataset = environment["SOURCE_DATASET"]
    discovered = discover_latest_parquet(
        s3_client,
        source_bucket=source_bucket,
        source_prefix=source_prefix,
    )
    message = {
        "dataset": dataset,
        "source_bucket": source_bucket,
        "source_key": discovered["key"],
        "source_size": discovered["size"],
        "source_etag": discovered["etag"],
        "source_last_modified": discovered["last_modified"],
    }
    response = sqs_client.send_message(
        QueueUrl=environment["INGESTION_QUEUE_URL"],
        MessageBody=json.dumps(message),
    )
    return {
        "dataset": dataset,
        "source_key": str(discovered["key"]),
        "message_id": response["MessageId"],
    }


def copy_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    lambda_client: Any | None = None,
    environment: dict[str, str] | None = None,
    now: Any | None = None,
) -> dict[str, list[dict[str, str]]]:
    del context
    env = environment if environment is not None else dict(os.environ)
    client = s3_client or boto3.client("s3", region_name="us-west-2")
    function_client = lambda_client
    if function_client is None and env.get("MATERIALIZATION_FUNCTION"):
        function_client = boto3.client("lambda", region_name="us-west-2")
    clock = now or (lambda: datetime.now(UTC))
    failures = []

    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            source_key = message["source_key"]
            filename = PurePosixPath(source_key).name
            year_month = filename.rsplit("_", 2)[-2:]
            year = year_month[0]
            month = year_month[1].removesuffix(".parquet")
            raw_key = (
                f"raw/ons/{message['dataset']}/source_year={year}/source_month={month}/{filename}"
            )

            response = client.get_object(
                Bucket=message["source_bucket"],
                Key=source_key,
            )
            sha256 = hashlib.sha256()
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as body:
                for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    sha256.update(chunk)
                    body.write(chunk)
                body.seek(0)
                client.upload_fileobj(
                    body,
                    env["DATA_BUCKET"],
                    raw_key,
                    ExtraArgs={
                        "ContentType": "application/vnd.apache.parquet",
                        "Metadata": {
                            "source-bucket": message["source_bucket"],
                            "source-key": source_key,
                            "source-etag": message["source_etag"],
                            "sha256": sha256.hexdigest(),
                        },
                    },
                )

            collected_at = clock()
            manifest_key = (
                f"manifests/{message['dataset']}/"
                f"ingestion_date={collected_at.date().isoformat()}/"
                f"{filename.removesuffix('.parquet')}.json"
            )
            manifest = {
                "dataset": message["dataset"],
                "source_url": f"s3://{message['source_bucket']}/{source_key}",
                "source_key": source_key,
                "source_size": message["source_size"],
                "source_etag": message["source_etag"],
                "source_last_modified": message["source_last_modified"],
                "destination_key": raw_key,
                "sha256": sha256.hexdigest(),
                "collected_at": collected_at.isoformat(),
                "validation_status": "pending",
            }
            client.put_object(
                Bucket=env["DATA_BUCKET"],
                Key=manifest_key,
                Body=json.dumps(manifest, ensure_ascii=False).encode(),
                ContentType="application/json",
            )
            if function_client is not None and env.get("MATERIALIZATION_FUNCTION"):
                function_client.invoke(
                    FunctionName=env["MATERIALIZATION_FUNCTION"],
                    InvocationType="Event",
                    Payload=json.dumps(
                        {
                            "bucket": env["DATA_BUCKET"],
                            "key": raw_key,
                            "sha256": sha256.hexdigest(),
                            "manifest_key": manifest_key,
                        }
                    ).encode(),
                )
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failures}
