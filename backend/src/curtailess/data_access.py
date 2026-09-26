import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3


class ExposureRepository:
    def __init__(self, table: Any):
        self.table = table

    def list_assets(self) -> list[dict[str, Any]]:
        response = self.table.scan()
        latest: dict[str, dict[str, Any]] = {}
        for item in response.get("Items", []):
            period = item.get("period", "")
            if "#" in period:
                continue
            asset_id = item["asset_id"]
            if asset_id not in latest or period > latest[asset_id]["period"]:
                latest[asset_id] = item
        return [latest[asset_id] for asset_id in sorted(latest)]

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        items = [item for item in self.list_assets() if item["asset_id"] == asset_id]
        return items[0] if items else None

    def get_exposure(self, asset_id: str, start: date, end: date) -> dict[str, Any] | None:
        response = self.table.scan()
        items = [
            item
            for item in response.get("Items", [])
            if item["asset_id"] == asset_id
            and "#" not in item["period"]
            and date.fromisoformat(item["period_start"][:10]) <= end
            and date.fromisoformat(item["period_end"][:10]) >= start
        ]
        if not items:
            return None
        items.sort(key=lambda item: item["period"])
        return {
            "curtailed_mwh": sum((item["curtailed_mwh"] for item in items), start=Decimal("0")),
            "periods": [item["period"] for item in items],
            "source_sha256s": [item["source_sha256"] for item in items],
            "items": items,
        }

    def get_point_context(self, asset_id: str) -> dict[str, Any] | None:
        asset = self.get_asset(asset_id)
        if asset is None:
            return None
        response = self.table.scan()
        items = [
            item
            for item in response.get("Items", [])
            if "#" not in item["period"] and item.get("point_id") == asset["point_id"]
        ]
        latest_by_asset: dict[str, dict[str, Any]] = {}
        for item in items:
            current = latest_by_asset.get(item["asset_id"])
            if current is None or item["period"] > current["period"]:
                latest_by_asset[item["asset_id"]] = item
        latest = list(latest_by_asset.values())
        limited_count = sum(item.get("limited_interval_count", 0) > 0 for item in latest)
        point_hash = hashlib.sha256(asset["point_id"].encode()).hexdigest()[:12]
        return {
            "connection_point": f"point-{point_hash}",
            "entity_count": len(latest),
            "limited_entity_count": limited_count,
            "period_start": min(item["period_start"][:10] for item in latest),
            "period_end": max(item["period_end"][:10] for item in latest),
            "data_version": ",".join(sorted({item["period"] for item in latest})),
            "source_sha256s": sorted({item["source_sha256"] for item in latest}),
        }

    def get_historical_windows(
        self, asset_id: str, start: date, end: date, duration_hours: int
    ) -> list[dict[str, Any]]:
        exposure = self.get_exposure(asset_id, start, end)
        if exposure is None:
            return []
        windows = []
        for item in exposure["items"]:
            window_start = datetime.fromisoformat(item["period_start"]).replace(tzinfo=UTC)
            window_end = window_start + timedelta(hours=duration_hours)
            observed_hours = Decimal(str(item["interval_count"])) * Decimal("0.5")
            curtailed_mwh = (
                Decimal(str(item["curtailed_mwh"])) * Decimal(duration_hours) / observed_hours
                if observed_hours
                else Decimal(0)
            )
            windows.append(
                {
                    "start": window_start,
                    "end": window_end,
                    "curtailed_mwh": round(float(curtailed_mwh), 6),
                    "period": item["period"],
                    "source_sha256": item["source_sha256"],
                    "method": "monthly_observed_rate_prorated_to_window_v1",
                }
            )
        return windows


class UnconfiguredExposureRepository:
    def list_assets(self) -> list[dict[str, Any]]:
        return []

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        del asset_id
        return None

    def get_exposure(self, asset_id: str, start: date, end: date) -> None:
        del asset_id, start, end
        return None

    def get_point_context(self, asset_id: str) -> None:
        del asset_id
        return None

    def get_historical_windows(
        self, asset_id: str, start: date, end: date, duration_hours: int
    ) -> list[dict[str, Any]]:
        del asset_id, start, end, duration_hours
        return []


def create_exposure_repository(table_name: str | None, region_name: str) -> Any:
    if not table_name:
        return UnconfiguredExposureRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return ExposureRepository(table)
