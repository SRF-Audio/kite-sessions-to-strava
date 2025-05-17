import os
import sys
import logging
import datetime
import requests
import gpxpy
import gpxpy.gpx
from pathlib import Path
from typing import Optional, List, Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

class StravaAuthError(Exception):
    """Custom exception for Strava authentication errors."""
    pass

def get_strava_access_token() -> str:
    """
    Retrieve a valid Strava access token. You’ll typically need:
      - STRAVA_CLIENT_ID
      - STRAVA_CLIENT_SECRET
      - STRAVA_REFRESH_TOKEN

    For brevity, this example fetches them from environment variables.
    In a production setup, you’d refresh the token if needed, etc.
    """
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        raise StravaAuthError("Missing Strava environment variables for auth.")

    token_url = "https://www.strava.com/oauth/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    try:
        resp = requests.post(token_url, data=data, timeout=10)
        resp.raise_for_status()
        access_token = resp.json()["access_token"]
        return access_token
    except requests.exceptions.RequestException as e:
        raise StravaAuthError(
            f"Failed to retrieve Strava access token: {str(e)}"
        ) from e

def test_strava_credentials(token: str) -> bool:
    """
    Makes a simple GET request to Strava’s athlete endpoint
    to validate our token works.
    Returns True if the credentials are valid, False otherwise.
    """
    url = "https://www.strava.com/api/v3/athlete"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            logging.info("Strava credentials validated successfully.")
            return True
        else:
            logging.warning(
                f"Strava credential test failed. Status code: {resp.status_code}"
            )
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error while testing Strava credentials: {e}")
        return False

def list_gpx_files(directory: str) -> List[Path]:
    """
    Retrieve a comprehensive list of .gpx files from the specified folder.
    """
    path_obj = Path(directory)
    if not path_obj.is_dir():
        logging.error(f"Provided path {directory} is not a directory.")
        return []
    gpx_files = list(path_obj.rglob("*.gpx"))
    logging.info(f"Found {len(gpx_files)} GPX files in {directory}")
    return gpx_files

def parse_gpx_metadata(gpx_file: Path) -> Optional[Dict[str, str]]:
    """
    Parse the GPX file’s metadata for name and time.
    Returns a dict with keys 'name' and 'time' if found, else None.
    """
    try:
        with open(gpx_file, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
            if gpx.metadata and gpx.metadata.name and gpx.metadata.time:
                metadata = {
                    "name": gpx.metadata.name,
                    "time": gpx.metadata.time.isoformat()  # e.g. 2025-04-13T20:35:29
                }
                return metadata
            else:
                logging.warning(f"No valid metadata found in {gpx_file}")
                return None
    except Exception as e:
        logging.error(f"Failed to parse GPX file {gpx_file}: {e}")
        return None

def activity_exists_in_strava(
    token: str, activity_time_utc: str
) -> bool:
    """
    Check if an activity with the same start date/time is already on Strava.
    One approach is to filter athlete activities by date range that covers
    the day in question, then compare the 'start_date' fields.

    A more efficient solution might be possible if you store references
    to known activity IDs, but here we illustrate a straightforward method:
      1. Convert GPX time to a timestamp (UTC).
      2. Query /athlete/activities within that day’s range.
      3. Check for an exact match in the results.
    """
    # Convert ISO 8601 to a datetime
    # e.g. 2025-04-13T20:35:29 --> datetime object in UTC
    try:
        dt_utc = datetime.datetime.fromisoformat(activity_time_utc.replace("Z", "+00:00"))
    except ValueError:
        logging.error(f"Invalid time format: {activity_time_utc}")
        return False

    # We'll look up from midnight to midnight of that day:
    day_start = datetime.datetime(dt_utc.year, dt_utc.month, dt_utc.day, 0, 0, 0, tzinfo=dt_utc.tzinfo)
    day_end = day_start + datetime.timedelta(days=1)

    after_unix = int(day_start.timestamp())
    before_unix = int(day_end.timestamp())

    url = (
        "https://www.strava.com/api/v3/athlete/activities"
        f"?after={after_unix}&before={before_unix}&per_page=100"
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        activities = resp.json()  # list of activities
    except requests.exceptions.RequestException as e:
        logging.error(f"Error listing Strava activities: {e}")
        # If there's an error, treat it as "not found" to avoid duplicates,
        # or raise an exception. Customize as needed.
        return False

    # We'll compare the exact string, or you could parse them as datetime
    # objects if you want to check with some tolerance.
    for activity in activities:
        start_date = activity.get("start_date")  # e.g. "2025-04-13T20:35:29Z"
        if not start_date:
            continue
        # Convert Strava start_date to a datetime
        try:
            start_dt_utc = datetime.datetime.fromisoformat(
                start_date.replace("Z", "+00:00")
            )
            # If the difference is very small (a few seconds), we treat it as same:
            if abs((start_dt_utc - dt_utc).total_seconds()) < 5:
                logging.info("Found existing activity matching GPX start date.")
                return True
        except ValueError:
            continue

    return False

def upload_gpx_to_strava(token: str, gpx_file: Path) -> bool:
    """
    Perform a POST to the Strava upload endpoint with the GPX file.
    Returns True if upload initiated successfully, else False.

    The actual processing of the uploaded file on Strava’s side
    happens asynchronously, so you may want to poll the upload
    endpoint if you care about final success/failure.
    """
    url = "https://www.strava.com/api/v3/uploads"
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file": (gpx_file.name, open(gpx_file, "rb"), "application/gpx+xml")
    }
    data = {
        "data_type": "gpx",
        # Optional fields. For example:
        # "name": "My Activity",
        # "description": "Uploaded via API",
        # "trainer": "false",
        # "commute": "false",
    }

    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        resp.raise_for_status()
        json_resp = resp.json()
        logging.info(f"Upload response from Strava: {json_resp}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Error uploading {gpx_file} to Strava: {e}")
        return False
    finally:
        # Make sure the file handle is closed
        for file in files.values():
            file[1].close()

def main():
    """
    Main orchestrator:
      1. Get auth token & test credentials.
      2. Collect GPX files from folder.
      3. For each GPX, parse metadata.
      4. Check if the activity time matches an existing Strava activity.
      5. If not found, upload to Strava.
    """
    # In a real script, read this from sys.argv, config, etc.
    directory_to_scan = "./gpx_folder"

    # 1. Authenticate
    try:
        token = get_strava_access_token()
    except StravaAuthError as e:
        logging.error(f"Strava auth error: {e}")
        sys.exit(1)

    if not test_strava_credentials(token):
        logging.error("Strava credentials are not valid; exiting.")
        sys.exit(1)

    # 2. Retrieve .gpx files
    gpx_files = list_gpx_files(directory_to_scan)
    if not gpx_files:
        logging.info("No GPX files found, or invalid directory. Exiting.")
        return

    # 3. For each GPX, parse metadata
    for gpx_file in gpx_files:
        metadata = parse_gpx_metadata(gpx_file)
        if not metadata:
            # Skip if no metadata
            continue

        # 4. Check if activity already exists
        already_exists = activity_exists_in_strava(token, metadata["time"])
        if already_exists:
            logging.info(f"GPX file {gpx_file} already exists in Strava. Skipping.")
            continue

        # 5. Upload it
        success = upload_gpx_to_strava(token, gpx_file)
        if success:
            logging.info(f"Successfully initiated upload for {gpx_file}.")
        else:
            logging.error(f"Upload failed for {gpx_file}.")

if __name__ == "__main__":
    main()
