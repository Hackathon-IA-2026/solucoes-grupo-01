import json
from typing import Any

import boto3


class ArtifactRepository:
    def __init__(self, table: Any, bucket: str, s3_client: Any):
        self.table = table
        self.bucket = bucket
        self.s3_client = s3_client

    def create_report(self, report: dict[str, Any]) -> dict[str, Any]:
        item = report.copy()
        body = item.pop("body")
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=item["artifact_key"],
            Body=body.encode(),
            ContentType="application/json",
        )
        self.table.put_item(Item=item)
        return item

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"plant_id": "REPORT", "scenario_id": report_id})
        return response.get("Item")

    def get_report_file_url(self, report: dict[str, Any]) -> str:
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": report["artifact_key"]},
            ExpiresIn=300,
        )


class UnconfiguredArtifactRepository:
    def create_report(self, report: dict[str, Any]) -> dict[str, Any]:
        del report
        raise RuntimeError("Repositório de artefatos não configurado.")

    def get_report(self, report_id: str) -> None:
        del report_id
        return None

    def get_report_file_url(self, report: dict[str, Any]) -> str:
        del report
        raise RuntimeError("Repositório de artefatos não configurado.")


def create_artifact_repository(
    table_name: str | None, bucket: str | None, region_name: str
) -> ArtifactRepository | UnconfiguredArtifactRepository:
    if not table_name or not bucket:
        return UnconfiguredArtifactRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    s3_client = boto3.client("s3", region_name=region_name)
    return ArtifactRepository(table, bucket, s3_client)


def serialize_report_body(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
