import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

# Import other modules here (after basicConfig so they inherit the config)
import strava_client
import gpx_handler


logger = logging.getLogger(__name__)

if __name__ == "__main__":
    gpx_path = "./gpx_files"
    
    logger.info("Starting Strava GPX uploader.")

    strava = strava_client.StravaClient()

    gpx = gpx_handler.GPXHandler(gpx_path)
    gpx.display_all_gpx()
    # Use this block to call the API when needed
    # current_strava_activities = strava.get_logged_in_athlete_activities()

    # strava.save_activities_as_json(current_strava_activities)

