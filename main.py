import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

if __name__ == "__main__":
    logging.info("Kite Strava integration started.")