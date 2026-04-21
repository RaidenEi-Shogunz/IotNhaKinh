"""
Nha Kinh Thong Minh - Cau hinh he thong
=========================================
Tat ca hang so cau hinh tap trung tai day.
Load ADAFRUIT_USERNAME va ADAFRUIT_KEY tu file .env.

FIX [1]: RATE_LIMIT_MIN_INTERVAL tang len 22s
         9 feeds x (60/22) = 24.5/phut < 30 limit (Adafruit IO Free)
FIX [2]: TASK_INTERVAL_MQTT dong bo chinh xac voi RATE_LIMIT_MIN_INTERVAL
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Ket noi MQTT Broker (Adafruit IO)
# ============================================================
ADAFRUIT_USERNAME = os.getenv("ADAFRUIT_USERNAME", "")
ADAFRUIT_KEY      = os.getenv("ADAFRUIT_KEY", "")

MQTT_HOST      = "io.adafruit.com"
MQTT_PORT      = 1883
MQTT_KEEPALIVE = 60
MQTT_QOS       = 1
MQTT_RETAIN    = False

# ============================================================
# Feeds MQTT
# ============================================================
FEED_SOIL_MOISTURE  = "soil-moisture"
FEED_TEMPERATURE    = "temperature"
FEED_LIGHT          = "light-intensity"
FEED_HUMIDITY       = "humidity"
FEED_CO2            = "co2-level"
FEED_PUMP_STATUS    = "pump-status"
FEED_PUMP_CMD       = "pump-cmd"
FEED_MODE           = "greenhouse-mode"
FEED_THRESHOLD      = "moisture-threshold"
FEED_AI_STATUS      = "ai-status"
FEED_WATERING_EVENT = "watering-event"
FEED_ALERT          = "alert-status"

def get_topic(feed_name):
    """Tao topic MQTT day du tu ten feed."""
    return f"{ADAFRUIT_USERNAME}/feeds/{feed_name}"

# ============================================================
# Rate Limiter (Adafruit IO Free: 30 data points / phut)
# FIX: 9 feeds x (60/22s) = ~24.5/phut  -->  an toan duoi 30
# ============================================================
RATE_LIMIT_POINTS_PER_MIN    = 30
RATE_LIMIT_FEEDS_PER_PUBLISH = 9
RATE_LIMIT_MIN_INTERVAL      = 30   # FIX: tang tu 15 -> 22 giay

# ============================================================
# Thong so mo phong
# ============================================================
TIME_SCALE     = 10
DAY_START_HOUR = 6
DAY_END_HOUR   = 20

TEMP_DAY_BASE   = 30.0
TEMP_NIGHT_BASE = 20.0
TEMP_NOISE      = 0.3
TEMP_MAX        = 40.0
TEMP_MIN        = 10.0
THERMAL_INERTIA = 0.7

LIGHT_DAY_MAX   = 10000
LIGHT_NIGHT_MAX = 5
LIGHT_NOISE     = 50

MOISTURE_INIT        = 50.0
MOISTURE_LOW         = 30.0
MOISTURE_HIGH        = 70.0
MOISTURE_TARGET      = 50.0
MOISTURE_MIN_CLAMP   = 5.0
MOISTURE_MAX_CLAMP   = 99.0
MOISTURE_DECAY_DAY   = 0.15
MOISTURE_DECAY_NIGHT = 0.05
MOISTURE_PUMP_RATE   = 3.0
MOISTURE_RAIN_RATE   = 0.5

HUMIDITY_BASE      = 65.0
HUMIDITY_AMPLITUDE = 15.0
HUMIDITY_NOISE     = 1.0
HUMIDITY_MIN       = 30.0
HUMIDITY_MAX       = 90.0

CO2_BASE       = 450.0
CO2_DAY_DROP   = 80.0
CO2_NIGHT_RISE = 60.0
CO2_NOISE      = 10.0
CO2_MAX        = 1000.0

WEATHER_EVENT_CHANCE        = 0.01
WEATHER_RAIN_DURATION       = 2.0
WEATHER_CLOUD_DURATION      = 3.0
WEATHER_RAIN_PUMP_THRESHOLD = 0.4

PID_ENABLED      = True
PID_KP           = 2.0
PID_KI           = 0.1
PID_KD           = 0.5
PID_INTEGRAL_MAX = 50.0
PID_OUTPUT_MIN   = 0.0
PID_OUTPUT_MAX   = 100.0

DB_PATH          = "dulieu_nhakinh.db"
DB_MAX_RECORDS   = 10000
DB_CLEANUP_BATCH = 1000

ALERT_COOLDOWN    = 300
ALERT_MAX_HISTORY = 200

# ============================================================
# Scheduler intervals (giay)
# FIX: TASK_INTERVAL_MQTT = RATE_LIMIT_MIN_INTERVAL = 22
# ============================================================
SCHEDULER_TICK             = 0.5
TASK_INTERVAL_ENVIRONMENT  = 5
TASK_INTERVAL_PUMP         = 3
TASK_INTERVAL_MQTT         = 22    # FIX: dong bo voi RATE_LIMIT_MIN_INTERVAL
TASK_INTERVAL_AI           = 30
TASK_INTERVAL_ALERT        = 5
TASK_INTERVAL_PERSISTENCE  = 30

WATCHDOG_ENABLED = True
WATCHDOG_TIMEOUT = 10.0

def validate():
    errors = []
    if not ADAFRUIT_USERNAME:
        errors.append("ADAFRUIT_USERNAME chua duoc cau hinh trong .env")
    if not ADAFRUIT_KEY:
        errors.append("ADAFRUIT_KEY chua duoc cau hinh trong .env")
    if TASK_INTERVAL_MQTT < RATE_LIMIT_MIN_INTERVAL:
        errors.append(
            f"TASK_INTERVAL_MQTT ({TASK_INTERVAL_MQTT}) phai >= "
            f"RATE_LIMIT_MIN_INTERVAL ({RATE_LIMIT_MIN_INTERVAL})"
        )
    return errors

_validation_errors = validate()
