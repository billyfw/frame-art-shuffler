"""Constants for the Frame Art Shuffler integration."""

from pathlib import Path

DOMAIN = "frame_art_shuffler"
DEFAULT_PORT = 8002
DEFAULT_TIMEOUT = 30

# Tokens live alongside the integration so they ship with the add-on/config backup.
TOKEN_DIR = Path(__file__).resolve().parent / "tokens"
