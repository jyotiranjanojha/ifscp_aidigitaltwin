from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Optional

import duckdb
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TimeBucket:
    bucket_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarInterval:
    cal_id: str
    start_date: date
    end_date: date
    pattern_seq_num: Optional[str]
    weekday_mask: frozenset[int]
    attribute_value: Optional[float]
    start_time: Optional[time]
    end_time: Optional[time]


class CalendarResolver:
    """Resolve native Blue Yonder calendar references into time-phased parameters."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, default_hours: float = 24.0) -> None:
        self.conn = conn
        self.default_hours = default_hours
        self.calendars = self._table("calendars")
        self.calpattern = self._table("calpattern")
        self.calattribute = self._table("calattribute")
        self.res = self._table("res")
        self.billofmaterials = self._table("billofmaterials")
        self.sourcing = self._table("sourcing")
        self.network = self._table("network")

        self.calendar_type_by_cal = self._calendar_types()
        self.attribute_by_cal_pattern = self._attribute_lookup()
        self.index: dict[str, list[CalendarInterval]] = self._build_index()

    @classmethod
    def from_duckdb(cls, conn: duckdb.DuckDBPyConnection, default_hours: float = 24.0) -> "CalendarResolver":
        return cls(conn, default_hours=default_hours)

    def resolve_calendar_value(self, cal_id: Optional[str], dt: datetime, default: Optional[float] = None) -> float:
        if not cal_id or pd.isna(cal_id):
            return self._default_value(cal_id, default)

        cal_key = str(cal_id)
        intervals = self.index.get(cal_key, [])
        target_date = dt.date()
        target_weekday = dt.isoweekday()
        target_time = dt.time()

        for interval in intervals:
            if not (interval.start_date <= target_date <= interval.end_date):
                continue
            if interval.start_time and interval.end_time and not self._time_contains(interval.start_time, interval.end_time, target_time):
                continue
            if interval.attribute_value is not None:
                return interval.attribute_value

        for interval in intervals:
            if not (interval.start_date <= target_date <= interval.end_date):
                continue
            if interval.weekday_mask and target_weekday not in interval.weekday_mask:
                continue
            if interval.start_time and interval.end_time:
                return self._duration_hours(interval.start_time, interval.end_time)
            return self._default_value(cal_key, default)

        return self._default_value(cal_key, default)

    def get_time_phased_resource_capacity(
        self,
        res_id: str,
        cal_id: str,
        bucket_start: datetime,
        bucket_end: datetime,
    ) -> float:
        if bucket_end <= bucket_start:
            return 0.0

        total_hours = 0.0
        cursor = bucket_start
        while cursor < bucket_end:
            next_midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min)
            segment_end = min(bucket_end, next_midnight)
            raw_hours = (segment_end - cursor).total_seconds() / 3600.0
            calendar_value = self.resolve_calendar_value(cal_id, cursor, default=1.0)
            if calendar_value <= 1.0:
                total_hours += raw_hours * max(calendar_value, 0.0)
            else:
                total_hours += min(raw_hours, calendar_value)
            cursor = segment_end
        return round(total_hours, 6)

    def get_time_phased_bom_yield(
        self,
        parent_item: str,
        subitem: str,
        ycal_id: str,
        bucket_start: datetime,
    ) -> float:
        if not ycal_id or pd.isna(ycal_id):
            return 1.0
        return round(self.resolve_calendar_value(ycal_id, bucket_start, default=1.0), 6)

    def generate_time_phased_model_parameters(self, horizon_buckets: list[TimeBucket]) -> dict[str, Any]:
        cap_matrix = self._build_resource_capacity_matrix(horizon_buckets)
        yield_matrix = self._build_yield_matrix(horizon_buckets)
        valid_ship_days = self._build_valid_ship_days_matrix(horizon_buckets)
        return {
            "CapMatrix": cap_matrix,
            "YieldMatrix": yield_matrix,
            "ValidShipDays": valid_ship_days,
            "CapArray": cap_matrix.to_numpy(dtype=float) if not cap_matrix.empty else np.empty((0, 0)),
            "YieldArray": yield_matrix.to_numpy(dtype=float) if not yield_matrix.empty else np.empty((0, 0)),
            "ValidShipDaysArray": valid_ship_days.to_numpy(dtype=float) if not valid_ship_days.empty else np.empty((0, 0)),
            "bucket_ids": [bucket.bucket_id for bucket in horizon_buckets],
        }

    def _build_index(self) -> dict[str, list[CalendarInterval]]:
        intervals: dict[str, list[CalendarInterval]] = defaultdict(list)
        if self.calpattern.empty:
            return intervals

        for row in self.calpattern.to_dict(orient="records"):
            cal_id = self._string_value(row.get("CAL"))
            if not cal_id:
                continue
            pattern_seq_num = self._string_value(row.get("PATTERNSEQNUM"))
            start_date = self._date_value(row.get("STARTDATE"), date.min)
            end_date = self._date_value(row.get("ENDDATE"), date.max)
            attributes = self.attribute_by_cal_pattern.get((cal_id, pattern_seq_num), [None])
            weekday_mask = self._weekday_mask(row)
            for attribute in attributes:
                intervals[cal_id].append(
                    CalendarInterval(
                        cal_id=cal_id,
                        start_date=start_date,
                        end_date=end_date,
                        pattern_seq_num=pattern_seq_num,
                        weekday_mask=weekday_mask,
                        attribute_value=attribute["value"] if attribute else None,
                        start_time=attribute["start_time"] if attribute else None,
                        end_time=attribute["end_time"] if attribute else None,
                    )
                )

        for cal_id, cal_intervals in intervals.items():
            intervals[cal_id] = sorted(cal_intervals, key=lambda item: (item.start_date, item.end_date))
        return intervals

    def _attribute_lookup(self) -> dict[tuple[str, Optional[str]], list[dict[str, Any]]]:
        lookup: dict[tuple[str, Optional[str]], list[dict[str, Any]]] = defaultdict(list)
        if self.calattribute.empty:
            return lookup

        for row in self.calattribute.to_dict(orient="records"):
            cal_id = self._string_value(row.get("CAL"))
            if not cal_id:
                continue
            pattern_seq_num = self._string_value(row.get("PATTERNSEQNUM"))
            lookup[(cal_id, pattern_seq_num)].append(
                {
                    "value": self._float_value(row.get("VALUE"), default=1.0),
                    "start_time": self._time_value(row.get("STARTTIME")),
                    "end_time": self._time_value(row.get("ENDTIME")),
                }
            )
        return lookup

    def _calendar_types(self) -> dict[str, Optional[float]]:
        if self.calendars.empty or "CAL" not in self.calendars.columns:
            return {}
        result = {}
        for row in self.calendars.to_dict(orient="records"):
            cal_id = self._string_value(row.get("CAL"))
            if cal_id:
                result[cal_id] = self._optional_float(row.get("TYPE"))
        return result

    def _build_resource_capacity_matrix(self, buckets: list[TimeBucket]) -> pd.DataFrame:
        if self.res.empty:
            return pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])
        rows = []
        for row in self.res.to_dict(orient="records"):
            res_id = self._string_value(row.get("RES") or row.get("RESOURCE"))
            loc = self._string_value(row.get("LOC"))
            cal_id = self._string_value(row.get("CAL") or row.get("CALENDAR"))
            if not res_id or not loc:
                continue
            rows.append(
                {
                    "RES": res_id,
                    "LOC": loc,
                    **{bucket.bucket_id: self.get_time_phased_resource_capacity(res_id, cal_id or "", bucket.start, bucket.end) for bucket in buckets},
                }
            )
        return pd.DataFrame(rows).set_index(["RES", "LOC"]) if rows else pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])

    def _build_yield_matrix(self, buckets: list[TimeBucket]) -> pd.DataFrame:
        if self.billofmaterials.empty:
            return pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])
        rows = []
        for row in self.billofmaterials.to_dict(orient="records"):
            parent = self._string_value(row.get("ITEM") or row.get("PARENT_ITEM"))
            subitem = self._string_value(row.get("SUBORD") or row.get("COMPONENT_ITEM"))
            ycal_id = self._string_value(row.get("YIELDCAL") or row.get("YCAL"))
            if not parent or not subitem:
                continue
            rows.append(
                {
                    "PARENT_ITEM": parent,
                    "SUBITEM": subitem,
                    **{bucket.bucket_id: self.get_time_phased_bom_yield(parent, subitem, ycal_id or "", bucket.start) for bucket in buckets},
                }
            )
        return pd.DataFrame(rows).set_index(["PARENT_ITEM", "SUBITEM"]) if rows else pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])

    def _build_valid_ship_days_matrix(self, buckets: list[TimeBucket]) -> pd.DataFrame:
        lane_rows = self.network if not self.network.empty else self.sourcing
        if lane_rows.empty:
            return pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])
        rows = []
        for row in lane_rows.to_dict(orient="records"):
            source = self._string_value(row.get("SOURCE"))
            dest = self._string_value(row.get("DEST"))
            cal_id = self._string_value(row.get("LEADTIMEEFFCNYCAL") or row.get("SHIPCAL") or row.get("CAL"))
            if not source or not dest:
                continue
            rows.append(
                {
                    "SOURCE": source,
                    "DEST": dest,
                    **{bucket.bucket_id: 1.0 if self.resolve_calendar_value(cal_id, bucket.start, default=1.0) > 0 else 0.0 for bucket in buckets},
                }
            )
        return pd.DataFrame(rows).drop_duplicates(subset=["SOURCE", "DEST"]).set_index(["SOURCE", "DEST"]) if rows else pd.DataFrame(columns=[bucket.bucket_id for bucket in buckets])

    def _table(self, table_name: str) -> pd.DataFrame:
        exists = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE lower(table_name) = ?
            """,
            [table_name.lower()],
        ).fetchone()[0]
        if not exists:
            return pd.DataFrame()
        df = self.conn.execute(f'SELECT * FROM "{table_name}"').fetchdf()
        df.columns = [self._normalize_column_name(column) for column in df.columns]
        return df

    def _weekday_mask(self, row: dict[str, Any]) -> frozenset[int]:
        day_columns = [
            ("MONDAYSW", 1),
            ("TUESDAYSW", 2),
            ("WEDNESDAYSW", 3),
            ("THURSDAYSW", 4),
            ("FRIDAYSW", 5),
            ("SATURDAYSW", 6),
            ("SUNDAYSW", 7),
        ]
        enabled = {day_num for column, day_num in day_columns if self._float_value(row.get(column), 0.0) > 0}
        day_value = self._optional_float(row.get("DAY"))
        if day_value and 1 <= day_value <= 7:
            enabled.add(int(day_value))
        return frozenset(enabled)

    def _default_value(self, cal_id: Optional[str], default: Optional[float]) -> float:
        if default is not None:
            return float(default)
        cal_type = self.calendar_type_by_cal.get(str(cal_id)) if cal_id else None
        return self.default_hours if cal_type in {1.0, 2.0} else 1.0

    def _date_value(self, value: Any, fallback: date) -> date:
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            return fallback
        return parsed.date()

    def _time_value(self, value: Any) -> Optional[time]:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.time()

    def _time_contains(self, start_time: time, end_time: time, target_time: time) -> bool:
        if start_time <= end_time:
            return start_time <= target_time <= end_time
        return target_time >= start_time or target_time <= end_time

    def _duration_hours(self, start_time: time, end_time: time) -> float:
        base = date(2000, 1, 1)
        start_dt = datetime.combine(base, start_time)
        end_dt = datetime.combine(base, end_time)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        return (end_dt - start_dt).total_seconds() / 3600.0

    def _float_value(self, value: Any, default: float = 0.0) -> float:
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _optional_float(self, value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _string_value(self, value: Any) -> Optional[str]:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _normalize_column_name(self, column: object) -> str:
        return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()