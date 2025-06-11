import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

# Import other modules here (after basicConfig so they inherit the config)
import strava_client
from pprint import pprint


logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Starting Strava GPX uploader.")

    strava = strava_client.StravaClient()

    current_strava_activities = strava.get_logged_in_athlete_activities()

    pprint(current_strava_activities)

