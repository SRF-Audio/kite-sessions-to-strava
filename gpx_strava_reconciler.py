"""
gpx_strava_reconciler.py

Single responsibility: decide which local GPX recordings are *not* already
on Strava and prepare payloads for the POST /api/v3/uploads endpoint.

Assumes:
    • 'strava' is an *instance* of StravaClient
    • 'gpx'    is an *instance* of GPXHandler
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Small helper dataclasses
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ActivitySignature:
    start_min: int  # minutes-since-epoch (UTC), rounded
    dur_min: int    # elapsed minutes, rounded
    lat4: float     # start-lat rounded to 4 decimals
    lon4: float     # start-lon rounded to 4 decimals


@dataclass(frozen=True, slots=True)
class GpxUploadJob:
    gpx_path: Path
    payload: Dict[str, Any]   # keys ready for Strava /uploads


# ──────────────────────────────────────────────────────────────────────────
# Core reconciler
# ──────────────────────────────────────────────────────────────────────────
class GPXStravaReconciler:
    _START_OFFSETS = range(-2, 3)   # ±2 minutes
    _DUR_OFFSETS   = range(-3, 4)   # ±3 minutes

    def __init__(self, strava_client, gpx_handler) -> None:
        self.strava = strava_client
        self.gpx_handler = gpx_handler
        self._index: Dict[ActivitySignature, int] = {}
        self._build_strava_index()

    # ––––– public API –––––
    def reconcile(self) -> List[GpxUploadJob]:
        jobs: List[GpxUploadJob] = []

        for gpx_path in self.gpx_handler:       # GPXHandler is iterable
            try:
                gpx_meta = self.gpx_handler.parse_gpx(gpx_path)
                sig = self._sig_from_gpx_meta(gpx_meta)
            except Exception as exc:            # noqa: BLE001
                logger.error("GPX parse failed for %s: %s", gpx_path.name, exc)
                continue

            dup_id = self._find_duplicate(sig)
            if dup_id:
                logger.info("Skipping %-30s (already on Strava id=%s)", gpx_path.name, dup_id)
                continue

            jobs.append(self._make_job(gpx_path))
            logger.info("Prepared upload for %s", gpx_path.name)

        logger.info("Prepared %d new upload(s) in total", len(jobs))
        return jobs

    # ––––– private helpers –––––
    def _build_strava_index(self) -> None:
        """One-time fetch & index of all existing activities."""
        logger.info("Building Strava activity index …")
        activities = self.strava.get_logged_in_athlete_activities()

        skipped = 0
        for act in activities:
            sig = self._sig_from_strava(act)
            if sig is None:
                skipped += 1
                logger.debug(
                    "Skipped activity with no usable GPS start point:\n%s",
                    json.dumps(act, indent=2, ensure_ascii=False),
                )
                continue
            self._index[sig] = act["id"]

        logger.info(
            "Indexed %d Strava activities (%d skipped for missing GPS)",
            len(self._index),
            skipped,
        )

    # signature builders ---------------------------------------------------
    @staticmethod
    def _round_min(dt: datetime) -> int:
        return int(round(dt.timestamp() / 60))  # minutes since epoch

    def _sig_from_gpx_meta(self, meta: Dict[str, Any]) -> ActivitySignature:
        start_ts: datetime = meta["start_ts_utc"]
        end_ts:   datetime = meta["end_ts_utc"]
        dur_min = int(round((end_ts - start_ts).total_seconds() / 60))
        lat, lon = meta["start_latlng"]
        return ActivitySignature(
            self._round_min(start_ts),
            dur_min,
            round(lat, 4),
            round(lon, 4),
        )

    def _sig_from_strava(self, act: Dict[str, Any]) -> ActivitySignature | None:
        start_utc = datetime.fromisoformat(act["start_date"].replace("Z", "+00:00"))
        dur_min   = int(round(act["elapsed_time"] / 60))

        coords = act.get("start_latlng", [])
        if len(coords) < 2:          # GPS-less or malformed entry
            return None
        lat, lon = coords

        return ActivitySignature(
            self._round_min(start_utc),
            dur_min,
            round(lat, 4),
            round(lon, 4),
        )

    # duplicate check ------------------------------------------------------
    def _find_duplicate(self, sig: ActivitySignature) -> int | None:
        """Return Strava activity-id if *sig* (or a fuzzy variant) exists."""
        m0  = sig.start_min
        d0  = sig.dur_min
        lat = sig.lat4
        lon = sig.lon4

        for dt in self._START_OFFSETS:
            for dd in self._DUR_OFFSETS:
                probe = ActivitySignature(m0 + dt, d0 + dd, lat, lon)
                if probe in self._index:
                    return self._index[probe]
        return None

    # payload prep ---------------------------------------------------------
    @staticmethod
    def _make_job(path: Path) -> GpxUploadJob:
        payload = {
            "data_type": "gpx",
            "external_id": path.name,
            "name": path.stem.replace("_", " "),
        }
        return GpxUploadJob(gpx_path=path, payload=payload)
