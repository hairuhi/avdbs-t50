import os
import json
import logging
import shutil
from typing import List, Set

HISTORY_FILE = "sent_posts.json"
TEMP_MEDIA_DIR = "temp_media"

def setup_logging():
    """Configures logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("crawler.log", encoding='utf-8')
        ]
    )

def load_history() -> List[str]:
    """Loads the list of sent post URLs from the history file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load history: {e}")
            return []
    return []

def save_history(history: List[str]):
    """Saves the list of sent post URLs to the history file."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save history: {e}")

def prepare_temp_dir():
    """Creates or cleans the temporary media directory."""
    if os.path.exists(TEMP_MEDIA_DIR):
        shutil.rmtree(TEMP_MEDIA_DIR, ignore_errors=True)
    os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

def cleanup_temp_dir():
    """Removes the temporary media directory."""
    if os.path.exists(TEMP_MEDIA_DIR):
        shutil.rmtree(TEMP_MEDIA_DIR, ignore_errors=True)
