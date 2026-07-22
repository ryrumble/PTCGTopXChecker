import logging
import os


def setup_logging() -> logging.Logger:
    """Configure application-wide logging: console only (no log files).

    Returns a configured logger. Safe to call multiple times.
    """
    logger = logging.getLogger("pkmn_topx")
    if logger.handlers:
        return logger

    level_name = os.environ.get("PKMN_TOPX_LOG_LEVEL", "INFO").upper()
    root_level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(root_level)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(root_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


logger = setup_logging()
