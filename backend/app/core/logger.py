import logging
import sys
from pathlib import Path
from rich.logging import RichHandler

def setup_logger(name: str = "exam_monitor"):
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)]
    )
    logger = logging.getLogger(name)
    return logger

logger = setup_logger()
