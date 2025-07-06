"""
GPX‑Strava reconciler
---------------------
Determine which local GPX tracks are **not** yet on Strava and build
ready‑to‑upload payloads for the POST ``/api/v3/uploads`` endpoint.

Assumptions
~~~~~~~~~~~
* ``strava`` – an **instance** of :class:`StravaClient`
* ``gpx``    – an **instance** of :class:`GPXHandler`
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────
# Helper dataclasses
# ────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ActivitySignature:
    """A fuzzy fingerprint for duplicate detection."""

    start_min: int  # minutes‑since‑epoch (UTC), rounded
    dur_min: int    # elapsed minutes, rounded
    lat4: float     # start‑lat rounded to 4 decimals
    lon4: float     # start‑lon rounded to 4 decimals


@dataclass(frozen=True, slots=True)
class GpxUploadJob:
    gpx_path: Path
    payload: Dict[str, Any]  # keys expected by Strava ``/uploads``


# ────────────────────────────────────────────────────────────────────────────────
# GPX→Strava activity‑type mapping
# See <https://developers.strava.com/docs/reference/#api-models-SportType>
# ────────────────────────────────────────────────────────────────────────────────
_STRAVA_SPORT_MAP: dict[str | None, str] = {
    "Kiteboarding": "Kitesurf",
    "Kite Landboarding": "Kitesurf",  # closest native type
    "Windsurfing": "Windsurf",
    "Wing Foiling": "Windsurf",
    None: "Workout",  # fallback for unknown labels
}


# ────────────────────────────────────────────────────────────────────────────────
# Core reconciler
# ────────────────────────────────────────────────────────────────────────────────
class GPXStravaReconciler:
    """Build an index of Strava activities and prepare upload jobs."""

    _START_OFFSETS = range(-2, 3)   # ±2 minutes tolerance
    _DUR_OFFSETS = range(-3, 4)     # ±3 minutes tolerance

    def __init__(self, strava_client, gpx_handler) -> None:
        self.strava = strava_client
        self.gpx_handler = gpx_handler

        self._index: Dict[ActivitySignature, int] = {}
        self._build_strava_index()

    # ––––– public API –––––
    def reconcile(self) -> List[GpxUploadJob]:
        """Return a list of **new** :class:`GpxUploadJob` objects."""
        jobs: List[GpxUploadJob] = []

        for gpx_path in self.gpx_handler:  # ``GPXHandler`` is iterable
            try:
                gpx_meta = self.gpx_handler.parse_gpx(gpx_path)
                sig = self._sig_from_gpx_meta(gpx_meta)
            except Exception as exc:  # noqa: BLE001 – broad but logged
                logger.error("GPX parse failed for %s: %s", gpx_path.name, exc)
                continue

            dup_id = self._find_duplicate(sig)
            if dup_id:
                logger.info(
                    "Skipping %-30s (already on Strava id=%s)",
                    gpx_path.name,
                    dup_id,
                )
                continue

            jobs.append(self._make_job(gpx_path, gpx_meta))
            logger.info("Prepared upload for %s", gpx_path.name)

        logger.info("Prepared %d new upload(s) in total", len(jobs))
        return jobs

    # ––––– private helpers –––––
    def _build_strava_index(self) -> None:
        """Fetch all Strava activities once and build a lookup index."""
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
        """Round a *datetime* to the nearest minute and return minutes‑since‑epoch."""
        return int(round(dt.timestamp() / 60))

    def _sig_from_gpx_meta(self, meta: Dict[str, Any]) -> ActivitySignature:
        start_ts: datetime = meta["start_ts_utc"]
        end_ts: datetime = meta["end_ts_utc"]
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
        dur_min = int(round(act["elapsed_time"] / 60))

        coords = act.get("start_latlng", [])
        if len(coords) < 2:
            return None  # GPS‑less / malformed entry
        lat, lon = coords

        return ActivitySignature(
            self._round_min(start_utc),
            dur_min,
            round(lat, 4),
            round(lon, 4),
        )

    # duplicate check ------------------------------------------------------
    def _find_duplicate(self, sig: ActivitySignature) -> int | None:
        """Return Strava **activity‑id** if *sig* (or a fuzzy variant) exists."""
        m0 = sig.start_min
        d0 = sig.dur_min
        lat = sig.lat4
        lon = sig.lon4

        for dt in self._START_OFFSETS:
            for dd in self._DUR_OFFSETS:
                probe = ActivitySignature(m0 + dt, d0 + dd, lat, lon)
                if probe in self._index:
                    return self._index[probe]
        return None

    # payload prep ---------------------------------------------------------
    def _make_job(self, path: Path, meta: Dict[str, Any]) -> GpxUploadJob:
        """Build the multipart/form‑data *payload* Strava expects."""
        sport = _STRAVA_SPORT_MAP.get(meta.get("activity_type"), "Workout")

        payload: Dict[str, Any] = {
            "data_type": "gpx",
            # Strava uses ``external_id`` for duplicate detection on their side.
            "external_id": f"{path.stem}-{int(meta['start_ts_utc'].timestamp())}",
            "name": meta.get("activity_type") or path.stem.replace("_", " "),
            "sport_type": sport,
            "description": (
                f"Imported from {meta.get('source_app', 'GPX')} on "
                f"{meta['start_ts_utc'].date()}"
            ),
            "trainer": 0,  # 1 = stationary / turbo‑trainer
            "commute": 0,
            # "private": 1,  # uncomment if you prefer private by default
        }

        return GpxUploadJob(gpx_path=path, payload=payload)
