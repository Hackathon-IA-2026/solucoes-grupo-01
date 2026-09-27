import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3

MAX_EXPOSURE_QUERY_ITEMS = 33


class ExposureRepository:
    def __init__(self, table: Any):
        self.table = table

    def _scan_all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {}
        while True:
            response = self.table.scan(**request)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            request = {"ExclusiveStartKey": last_key}

    def _query_asset(
        self,
        asset_id: str,
        *,
        period_start: str | None = None,
        period_end: str | None = None,
        descending: bool = False,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        values = {":asset_id": asset_id}
        condition = "asset_id = :asset_id"
        if period_start is not None and period_end is not None:
            condition += " AND period BETWEEN :period_start AND :period_end"
            values.update({":period_start": period_start, ":period_end": period_end})
        request: dict[str, Any] = {
            "KeyConditionExpression": condition,
            "ExpressionAttributeValues": values,
            "ScanIndexForward": not descending,
        }
        if max_items is not None:
            request["Limit"] = max_items
        while True:
            response = self.table.query(**request)
            items.extend(
                item for item in response.get("Items", []) if "#" not in item.get("period", "")
            )
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            request["ExclusiveStartKey"] = last_key

    def list_assets(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for item in self._scan_all():
            period = item.get("period", "")
            if "#" in period:
                continue
            asset_id = item["asset_id"]
            if asset_id not in latest or period > latest[asset_id]["period"]:
                latest[asset_id] = item
        return [latest[asset_id] for asset_id in sorted(latest)]

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        items = self._query_asset(asset_id, descending=True, max_items=1)
        return items[0] if items else None

    def get_exposure(
        self, asset_id: str, start: date, end: date, reason: str | None = None
    ) -> dict[str, Any] | None:
        items = [
            item
            for item in self._query_asset(
                asset_id,
                period_start=start.strftime("%Y-%m"),
                period_end=f"{end.strftime('%Y-%m')}\uffff",
                max_items=MAX_EXPOSURE_QUERY_ITEMS,
            )
            if date.fromisoformat(item["period_start"][:10]) <= end
            and date.fromisoformat(item["period_end"][:10]) >= start
        ]
        if not items:
            return None
        items.sort(key=lambda item: item["period"])
        values = (
            (item.get("curtailed_mwh_by_reason", {}).get(reason, Decimal("0")) for item in items)
            if reason
            else (item["curtailed_mwh"] for item in items)
        )
        return {
            "curtailed_mwh": sum(values, start=Decimal("0")),
            "periods": [item["period"] for item in items],
            "source_sha256s": [item["source_sha256"] for item in items],
            "items": items,
        }

    def get_point_context(
        self, asset_id: str, asset: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        asset = asset or self.get_asset(asset_id)
        if asset is None:
            return None
        items = [
            item
            for item in self._scan_all()
            if "#" not in item["period"] and item.get("point_id") == asset["point_id"]
        ]
        latest_by_asset: dict[str, dict[str, Any]] = {}
        for item in items:
            current = latest_by_asset.get(item["asset_id"])
            if current is None or item["period"] > current["period"]:
                latest_by_asset[item["asset_id"]] = item
        latest = sorted(latest_by_asset.values(), key=lambda item: item["asset_id"])
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
            "items": latest,
        }

    def get_historical_windows(
        self,
        asset_id: str,
        start: date,
        end: date,
        duration_hours: int,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        exposure = self.get_exposure(asset_id, start, end, reason)
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
                    "method": (
                        "monthly_observed_reason_rate_prorated_to_window_v1"
                        if reason
                        else "monthly_observed_rate_prorated_to_window_v1"
                    ),
                }
            )
        return windows

    def get_data_quality(self, asset_id: str) -> dict[str, Any] | None:
        return self.get_asset(asset_id)

    def get_provenances(self, source_sha256s: set[str]) -> dict[str, dict[str, Any]]:
        matches: dict[str, list[dict[str, Any]]] = {value: [] for value in source_sha256s}
        for item in self._scan_all():
            if "#" in item["period"]:
                continue
            item_hashes = {item.get("source_sha256"), item.get("capacity_source_sha256")}
            for source_sha256 in source_sha256s.intersection(item_hashes):
                matches[source_sha256].append(item)
        results = {}
        for source_sha256, items in matches.items():
            if not items:
                continue
            items.sort(key=lambda item: (item["period"], item["asset_id"]), reverse=True)
            result = dict(items[0])
            result["asset_ids"] = sorted({item["asset_id"] for item in items})
            results[source_sha256] = result
        return results

    def get_provenance(self, source_sha256: str) -> dict[str, Any] | None:
        return self.get_provenances({source_sha256}).get(source_sha256)

    def get_materialization_run(self, period: str) -> dict[str, Any] | None:
        items = [item for item in self._scan_all() if item.get("period") == period]
        if not items:
            return None
        return {
            "period": period,
            "asset_count": len({item["asset_id"] for item in items}),
            "source_sha256s": sorted({item["source_sha256"] for item in items}),
        }


class UnconfiguredExposureRepository:
    def list_assets(self) -> list[dict[str, Any]]:
        return []

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        del asset_id
        return None

    def get_exposure(
        self, asset_id: str, start: date, end: date, reason: str | None = None
    ) -> None:
        del asset_id, start, end, reason
        return None

    def get_point_context(self, asset_id: str, asset: dict[str, Any] | None = None) -> None:
        del asset_id, asset
        return None

    def get_historical_windows(
        self,
        asset_id: str,
        start: date,
        end: date,
        duration_hours: int,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        del asset_id, start, end, duration_hours, reason
        return []

    def get_data_quality(self, asset_id: str) -> None:
        del asset_id
        return None

    def get_provenances(self, source_sha256s: set[str]) -> dict[str, dict[str, Any]]:
        del source_sha256s
        return {}

    def get_provenance(self, source_sha256: str) -> None:
        del source_sha256
        return None

    def get_materialization_run(self, period: str) -> None:
        del period
        return None


def create_exposure_repository(table_name: str | None, region_name: str) -> Any:
    if not table_name:
        return UnconfiguredExposureRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return ExposureRepository(table)
