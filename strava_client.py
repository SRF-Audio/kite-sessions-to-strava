import logging
import requests
import time
import os
import sys
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class StravaClient:
    def __init__(self):
        self.client_id = os.getenv("STRAVA_CLIENT_ID")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET")
        self.refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
        self.access_token = None
        self.expires_at = None  # Unix timestamp when token expires
        self.base_url = "https://www.strava.com/api/v3"

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            logger.error(
                """Missing required Strava API credentials in environment.

                    Expected environment variables:
                        STRAVA_CLIENT_ID
                        STRAVA_CLIENT_SECRET
                        STRAVA_REFRESH_TOKEN

                    Please set these and try again."""
            )
            sys.exit(1)
        self.authenticate()

    def authenticate(self):
        """
        Fully authenticate the session, using refresh_token flow.
        On success:
            - self.access_token is valid
            - self.expires_at is set
            - self.refresh_token is updated if rotated
        """
        token_url = "https://www.strava.com/oauth/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        logger.info("Authenticating with Strava API using refresh_token...")

        try:
            response = requests.post(token_url, data=data, timeout=10)
            response.raise_for_status()
            token_data = response.json()

            # Extract token fields
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            self.expires_at = token_data.get("expires_at")

            if not self.access_token or not self.expires_at:
                logger.error(
                    "Strava token response missing required fields: %s", token_data
                )
                raise RuntimeError("Incomplete token response from Strava.")

            # Log success with readable expiry
            expires_in_sec = self.expires_at - int(time.time())
            logger.info(
                "Strava authentication successful. Token expires in %d minutes.",
                expires_in_sec // 60
            )

        except requests.exceptions.RequestException as e:
            logger.error("Error during Strava authentication: %s", str(e))
            raise

        except Exception as e:
            logger.exception("Unexpected error during Strava authentication.")
            raise

    def get_logged_in_athlete_activities(self):
        """
        Retrieve ALL athlete activities across ALL pages.
        Returns a list of activity dicts.

        NOTE: No filtering is done here — caller is responsible for any filtering.
        """
        logger.info("Fetching ALL athlete activities from Strava...")

        activities = []
        page = 1
        per_page = 100  # Max allowed by Strava

        while True:
            params = {
                "page": page,
                "per_page": per_page
            }

            url = f"{self.base_url}/athlete/activities"

            try:
                response = requests.get(
                    url,
                    headers = {
                        "Authorization": f"Bearer {self.access_token}"
                    },
                    params=params,
                    timeout=10
                )
                response.raise_for_status()
                page_activities = response.json()
            except requests.exceptions.RequestException as e:
                logger.error("Error fetching activities on page %d: %s", page, str(e))
                raise

            if not page_activities:
                logger.info("No more activities found (page %d empty).", page)
                break

            logger.info("Fetched page %d with %d activities.", page, len(page_activities))
            activities.extend(page_activities)
            page += 1

        logger.info("Total activities fetched: %d", len(activities))
        return activities

    def save_activities_as_json(
        self,
        activities: list[dict],
        output_dir: str | Path = "."
    ) -> Path:
        """
        Persist a list of activity dictionaries to a timestamp-named, pretty-printed
        JSON file.

        Args:
            activities: The iterable returned by ``get_logged_in_athlete_activities``.
            output_dir: Directory in which to place the file (default: current dir).

        Returns:
            pathlib.Path pointing to the file that was written.

        Raises:
            OSError: If *output_dir* is not writable.
        """
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)   # ⇐ create ./outputs if absent

        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = f"strava_activities_{ts}.json"
        path = out_dir / filename

        logger.info("Writing %d activities to %s", len(activities), path)

        with path.open("w", encoding="utf-8") as fp:
            json.dump(activities, fp, ensure_ascii=False, indent=2)

        logger.info("Successfully wrote activities JSON to %s (%.1f KB)",
                    path, path.stat().st_size / 1024)
        return path
    