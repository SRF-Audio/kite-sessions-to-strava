"""Strava API convenience wrapper
================================
· OAuth2 refresh‑token flow
· Read **and** write helpers (upload GPX → activity)

The class focuses on:
---------------------
1. Handling token refresh transparently.
2. Downloading all athlete activities (used by the reconciler).
3. Uploading *GPX* files prepared by :pyclass:`GpxUploadJob`.

References
~~~~~~~~~~
* Strava OAuth: <https://developers.strava.com/docs/getting-started/>
* Uploads endpoint: <https://developers.strava.com/docs/uploads/>
* Model "SportType": <https://developers.strava.com/docs/reference/#api-models-SportType>
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class StravaAuthError(RuntimeError):
    """Raised when (re)authentication fails."""


class StravaUploadError(RuntimeError):
    """Raised when an upload returns a non‑success state."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class StravaClient:
    """Lightweight Strava API helper.

    The client expects the following **environment variables** to be set:

    * ``STRAVA_CLIENT_ID``
    * ``STRAVA_CLIENT_SECRET``
    * ``STRAVA_REFRESH_TOKEN``
    """

    BASE_URL = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"

    def __init__(self) -> None:
        self.client_id = os.getenv("STRAVA_CLIENT_ID")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET")
        self.refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            logger.error(
                "Missing Strava credentials. Ensure STRAVA_CLIENT_ID / _SECRET / _REFRESH_TOKEN are set."
            )
            sys.exit(1)

        self.access_token: Optional[str] = None
        self.expires_at: Optional[int] = None  # Unix ts

        self._authenticate()

    # ---------------------------------------------------------------------
    # Authentication helpers
    # ---------------------------------------------------------------------
    def _authenticate(self) -> None:
        """Refresh the access token (unconditionally)."""
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        logger.info("Authenticating with Strava (refresh‑token flow)…")

        try:
            resp = requests.post(self.TOKEN_URL, data=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise StravaAuthError(f"Token request failed: {exc}") from exc

        token_data = resp.json()
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]  # might rotate
        self.expires_at = token_data["expires_at"]

        ttl = self.expires_at - int(time.time())
        logger.info("Authentication OK – token valid for %.1f min", ttl / 60)

    # ---------------------------------------------------------------------
    # Low‑level request helper
    # ---------------------------------------------------------------------
    def _req(self, method: str, path: str, **kw):
        """Wrap *requests* with auto‑refresh + uniform error handling."""
        # Refresh if token is within 30 s of expiry
        if self.expires_at and time.time() > self.expires_at - 30:
            self._authenticate()

        kw.setdefault("timeout", 30)
        kw.setdefault("headers", {})
        kw["headers"].update({"Authorization": f"Bearer {self.access_token}"})

        url = f"{self.BASE_URL}{path}"

        try:
            resp = requests.request(method, url, **kw)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.error("Strava %s %s failed: %s", method, path, exc)
            raise

    # ---------------------------------------------------------------------
    # Public API – reads
    # ---------------------------------------------------------------------
    def get_logged_in_athlete_activities(self) -> List[Dict[str, Any]]:
        """Fetch **all** activities (paged)."""
        logger.info("Fetching ALL athlete activities…")
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = {"page": page, "per_page": 100}
            resp = self._req("GET", "/athlete/activities", params=params)
            batch = resp.json()
            if not batch:
                break
            logger.info("Fetched page %d (%d activities)", page, len(batch))
            out.extend(batch)
            page += 1
        logger.info("Total activities fetched: %d", len(out))
        return out

    # ---------------------------------------------------------------------
    # Public API – writes (uploads)
    # ---------------------------------------------------------------------
    def upload_gpx(self, job, *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
        """Upload a single :pyclass:`GpxUploadJob`.

        Parameters
        ----------
        job:
            Prepared job from the reconciler.
        dry_run:
            If *True*, **no request** is made; the payload is logged at INFO
            level instead. This is handy for verifying the upload body.
        """
        if dry_run:
            logger.info("DRY‑RUN — would POST /uploads with:\n%s",
                        json.dumps(job.payload, indent=2, ensure_ascii=False))
            return None

        files = {
            "file": (
                job.gpx_path.name,
                job.gpx_path.read_bytes(),
                "application/gpx+xml",
            )
        }
        resp = self._req("POST", "/uploads", data=job.payload, files=files)
        data = resp.json()
        logger.info("Upload accepted — upload_id=%s", data.get("id"))
        return data

    # ---------------------------------------------------------------------
    # Polling helper
    # ---------------------------------------------------------------------
    def poll_upload(self, upload_id: int, *, interval: int = 5, timeout: int = 180) -> int:
        """Poll ``/uploads/{id}`` until it becomes an activity or fails.

        Returns the new **activity_id** once available. Raises
        :class:`StravaUploadError` on error or timeout.
        """
        deadline = time.time() + timeout
        path = f"/uploads/{upload_id}"

        while time.time() < deadline:
            time.sleep(interval)
            data = self._req("GET", path).json()
            status = data.get("status")
            if status == "Your activity is ready.":
                logger.info("Upload %s processed → activity_id=%s", upload_id, data["activity_id"])
                return data["activity_id"]
            if status and status.startswith("There was an error"):
                raise StravaUploadError(data.get("error", "Unknown upload error"))
            logger.debug("Upload %s status: %s", upload_id, status)

        raise StravaUploadError(f"Timed out waiting for upload {upload_id} to finish")
