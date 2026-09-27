import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

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
        include_prefixed_periods: bool = False,
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
                item
                for item in response.get("Items", [])
                if include_prefixed_periods or "#" not in item.get("period", "")
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
            source_value = (
                item.get("curtailed_mwh_by_reason", {}).get(reason, Decimal("0"))
                if reason
                else item["curtailed_mwh"]
            )
            curtailed_mwh = (
                Decimal(str(source_value)) * Decimal(duration_hours) / observed_hours
                if observed_hours
                else Decimal(0)
            )
            windows.append(
                {
                    "start": window_start,
                    "end": window_end,
                    "curtailed_mwh": round(float(curtailed_mwh), 6),
                    "period": item["period"],
                    "source_key": item["source_key"],
                    "source_sha256": item["source_sha256"],
                    "method": (
                        "monthly_observed_reason_rate_prorated_to_window_v1"
                        if reason
                        else "monthly_observed_rate_prorated_to_window_v1"
                    ),
                    "source_record": item,
                }
            )
        return windows

    def get_forecast(self, program_entity_id: str, valid_at: datetime) -> dict[str, Any] | None:
        local_timezone = ZoneInfo("America/Sao_Paulo")
        if valid_at.tzinfo is None:
            target = valid_at.replace(tzinfo=local_timezone).isoformat()
        else:
            target = valid_at.astimezone(local_timezone).isoformat()
        candidates = []
        for item in self._query_asset(
            f"program:{program_entity_id.strip()}", include_prefixed_periods=True
        ):
            if item.get("fact_type") != "forecast_program_daily":
                continue
            for interval in item.get("intervals", []):
                if interval.get("valid_at") == target:
                    candidates.append(
                        {
                            **interval,
                            "program_entity_id": item["program_entity_id"],
                            "program_entity_name": item["program_entity_name"],
                            "publication_timestamp": item.get("publication_timestamp"),
                            "publication_time_status": item.get("publication_time_status"),
                            "source_key": item["source_key"],
                            "source_sha256": item["source_sha256"],
                            "source_fingerprint": item["source_fingerprint"],
                        }
                    )
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.get("publication_timestamp") or "",
                item["source_fingerprint"],
            ),
        )

    def get_generation_profiles(
        self,
        asset_id: str,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> list[dict[str, Any]]:
        profiles = [
            item
            for item in self._query_asset(asset_id, include_prefixed_periods=True)
            if item.get("fact_type") == "observed_generation_profile"
        ]
        if start_period is not None:
            profiles = [item for item in profiles if item["period"][11:] >= start_period]
        if end_period is not None:
            profiles = [item for item in profiles if item["period"][11:] <= end_period]
        return sorted(profiles, key=lambda item: item["period"])

    def get_identity(self, asset_id: str, as_of: date) -> dict[str, Any] | None:
        relationships = [
            item
            for item in self._query_asset(asset_id, include_prefixed_periods=True)
            if item.get("fact_type") == "asset_group_relationship"
            and (item.get("valid_from") is None or date.fromisoformat(item["valid_from"]) <= as_of)
            and (item.get("valid_to") is None or date.fromisoformat(item["valid_to"]) >= as_of)
        ]
        if not relationships:
            return None
        relationships.sort(
            key=lambda item: (item.get("valid_from") or "", item["period"]), reverse=True
        )
        identity = dict(relationships[0])
        ceg = identity.get("ceg")
        if ceg and ceg != "-":
            response = self.table.get_item(
                Key={"asset_id": f"ceg:{ceg}", "period": "identity#capacity#snapshot"},
                ConsistentRead=True,
            )
            if response.get("Item") is not None:
                identity["capacity"] = response["Item"]
        return identity

    def get_generation_profiles_by_technology_state(
        self, technology: str | None, state: str | None
    ) -> list[dict[str, Any]]:
        if not technology or not state:
            return []
        normalized = technology.strip().lower()
        technology_token = (
            "solar"
            if "solar" in normalized
            else "eoli"
            if "eoli" in normalized or normalized == "wind"
            else normalized
        )
        all_items = self._scan_all()
        latest_state: dict[str, tuple[str, str]] = {}
        for item in all_items:
            period = str(item.get("period", ""))
            item_state = item.get("state")
            if "#" in period or not item_state:
                continue
            current = latest_state.get(item["asset_id"])
            if current is None or period > current[0]:
                latest_state[item["asset_id"]] = (period, str(item_state))
        return sorted(
            (
                item
                for item in all_items
                if item.get("fact_type") == "observed_generation_profile"
                and technology_token in str(item.get("technology_name", "")).lower()
                and latest_state.get(item["asset_id"], ("", ""))[1] == state
            ),
            key=lambda item: (item["asset_id"], item["period"]),
        )

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

    def get_forecast(self, program_entity_id: str, valid_at: datetime) -> None:
        del program_entity_id, valid_at
        return None

    def get_generation_profiles(
        self,
        asset_id: str,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> list[dict[str, Any]]:
        del asset_id, start_period, end_period
        return []

    def get_identity(self, asset_id: str, as_of: date) -> None:
        del asset_id, as_of
        return None

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
