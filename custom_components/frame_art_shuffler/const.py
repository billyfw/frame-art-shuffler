"""Constants for the Frame Art Shuffler integration."""

DOMAIN = "frame_art_shuffler"
DEFAULT_PORT = 8002
DEFAULT_TIMEOUT = 30

DEFAULT_METADATA_RELATIVE_PATH = "www/frame_art/metadata.json"
TOKEN_DIR_NAME = "frame_art_shuffler/tokens"
LOG_STORAGE_RELATIVE_PATH = "frame_art/logs"
LOG_EVENTS_FILENAME = "events.json"
LOG_SUMMARY_FILENAME = "summary.json"
LOG_TAG_NONE = "<none>"

CONF_METADATA_PATH = "metadata_path"
CONF_TOKEN_DIR = "token_dir"
CONF_TAGS = "tags"
CONF_EXCLUDE_TAGS = "exclude_tags"
CONF_SHUFFLE_FREQUENCY = "shuffle_frequency_minutes"
CONF_NEXT_SHUFFLE_TIME = "next_shuffle_time"
CONF_ENABLE_AUTO_SHUFFLE = "enable_auto_shuffle"
CONF_TV_ID = "tv_id"
CONF_MOTION_SENSOR = "motion_sensor"
CONF_LIGHT_SENSOR = "light_sensor"
CONF_MIN_LUX = "min_lux"
CONF_MAX_LUX = "max_lux"
CONF_MIN_BRIGHTNESS = "min_brightness"
CONF_MAX_BRIGHTNESS = "max_brightness"
CONF_ENABLE_DYNAMIC_BRIGHTNESS = "enable_dynamic_brightness"
CONF_ENABLE_MOTION_CONTROL = "enable_motion_control"
CONF_MOTION_OFF_DELAY = "motion_off_delay"
CONF_LOGGING_ENABLED = "logging_enabled"
CONF_LOG_RETENTION_MONTHS = "log_retention_months"
CONF_LOG_FLUSH_MINUTES = "log_flush_interval_minutes"

DEFAULT_LOGGING_ENABLED = True
DEFAULT_LOG_RETENTION_MONTHS = 6
DEFAULT_LOG_FLUSH_MINUTES = 5

SIGNAL_SHUFFLE = f"{DOMAIN}_shuffle"
SIGNAL_AUTO_SHUFFLE_NEXT = f"{DOMAIN}_auto_shuffle_next"
