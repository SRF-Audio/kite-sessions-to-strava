import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)

if name == "__main__":
    # test logging
    logging.info("This is an info message.")