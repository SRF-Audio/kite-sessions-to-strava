"""GPX → Strava uploader entry‑point.

Run this script after placing GPX files in ``--gpx-dir``.  It will:

1. Display a summary of all GPX tracks found (via :class:`GPXHandler`).
2. Reconcile those tracks against *existing* Strava activities.
3. For each *new* track, upload it to Strava (unless ``--dry-run``).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from gpx_handler import GPXHandler  # local module
from gpx_strava_reconciler import GPXStravaReconciler
from strava_client import StravaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_DEF_GPX_DIR = Path("./gpx_files")


def _parse_args(argv: List[str] | None = None):  # noqa: D401
    """Return parsed CLI args."""
    p = argparse.ArgumentParser(description="Upload local GPX files to Strava.")
    p.add_argument(
        "--gpx-dir",
        type=Path,
        default=_DEF_GPX_DIR,
        help=f"Directory containing GPX files (default: {_DEF_GPX_DIR})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the upload payloads but do NOT call the Strava API.",
    )
    p.add_argument(
        "--no-poll",
        action="store_true",
        help="Don't poll Strava for processing status (faster).",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: List[str] | None = None):  # noqa: D401
    args = _parse_args(argv)

    logger.info("Starting Strava GPX uploader — dry_run=%s", args.dry_run)

    # 1. Initialise helpers ------------------------------------------------
    strava = StravaClient()
    gpx = GPXHandler(args.gpx_dir)

    gpx.display_all_gpx()

    reconciler = GPXStravaReconciler(strava, gpx)
    jobs = reconciler.reconcile()

    if not jobs:
        logger.info("Nothing new to upload – all caught up ✨")
        return 0

    # 2. Upload loop -------------------------------------------------------
    for job in jobs:
        try:
            resp = strava.upload_gpx(job, dry_run=args.dry_run)
            if args.dry_run or resp is None:
                continue  # next

            upload_id = resp["id"]
            if args.no_poll:
                logger.info(
                    "Queued %s (upload_id=%s) — not polling by request",
                    job.gpx_path.name,
                    upload_id,
                )
                continue

            activity_id = strava.poll_upload(upload_id)
            logger.info("Uploaded %s → activity %s", job.gpx_path.name, activity_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("FAILED upload for %s: %s", job.gpx_path.name, exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
