"""
Nha Kinh Thong Minh - Cau hinh he thong
=========================================
NANG CAP v3.0:
  [1] Them SENSOR_SPIKE_PROB va SENSOR_SPIKE_SIGMA (spike model linh hoat)
  [2] RATE_LIMIT_MIN_INTERVAL = 22s (9 feeds < 30/phut)
  [3] TASK_INTERVAL_MQTT = RATE_LIMIT_MIN_INTERVAL
  [4] Co chu thich ro vi sao khong nhan TIME_SCALE trong PID
"""

import os
import sys
import typing
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Ket noi MQTT Broker (Adafruit IO)
# ============================================================
ADAFRUIT_USERNAME = os.getenv("ADAFRUIT_USERNAME", "")
ADAFRUIT_KEY      = os.getenv("ADAFRUIT_KEY", "")

MQTT_HOST      = "io.adafruit.com"
MQTT_PORT      = 8883   # TLS/SSL
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
FEED_AI_CMD         = "ai-command"
FEED_WATERING_EVENT = "watering-event"
FEED_ALERT          = "alert-status"

def get_topic(feed_name):
    return f"{ADAFRUIT_USERNAME}/feeds/{feed_name}"

# ============================================================
# Rate Limiter (Adafruit IO Free: 30 data points / phut)
# 9 feeds x (60/22s) = ~24.5/phut  -> an toan duoi 30
# ============================================================
RATE_LIMIT_POINTS_PER_MIN    = 30
RATE_LIMIT_FEEDS_PER_PUBLISH = 9
RATE_LIMIT_MIN_INTERVAL      = 22

# ============================================================
# Thong so mo phong
# ============================================================
TIME_SCALE     = 10     # 1 phut thuc = 10 phut mo phong
DAY_START_HOUR = 6
DAY_END_HOUR   = 20

TEMP_DAY_BASE   = 30.0
TEMP_NIGHT_BASE = 20.0
TEMP_NOISE      = 0.3
TEMP_MAX        = 40.0
TEMP_MIN        = 10.0
THERMAL_INERTIA = 0.7   # Dung trong alpha = INERTIA^dt_factor

LIGHT_DAY_MAX  = 85000
LIGHT_NIGHT_MAX = 5
LIGHT_NOISE     = 50

# ============================================================
# Spike model (cam bien thuc te)
# Spike la outlier ngan han, xay ra ngau nhien
# SENSOR_SPIKE_PROB:  xac suat xay ra spike trong moi tick
# SENSOR_SPIKE_SIGMA: do lech chuan Gaussian cua spike (don vi do)
# ============================================================
SENSOR_SPIKE_PROB  = 0.02   # 2% moi tick co spike
SENSOR_SPIKE_SIGMA = 2.0    # Sigma cho nhiet do; do am, CO2 co sigma rieng

MOISTURE_INIT: float        = 50.0
MOISTURE_LOW: float         = 30.0
MOISTURE_HIGH: float        = 70.0
MOISTURE_TARGET: float      = 50.0
THRESHOLD_DEADBAND: float   = 2.0
MOISTURE_MIN_CLAMP: float   = 5.0
MOISTURE_MAX_CLAMP: float   = 99.0
MOISTURE_DECAY_DAY: float   = 0.15
MOISTURE_DECAY_NIGHT: float = 0.05
MOISTURE_PUMP_RATE: float   = 3.0
MOISTURE_RAIN_RATE: float   = 3.0

# ============================================================
# Mo hinh dat (Soil Model)
# ============================================================
SOIL_TYPE = "loam"
SOIL_PROPERTIES = {
    "sand": {"drainage_factor": 1.6, "absorption_factor": 1.4, "name": "Dat cat"},
    "loam": {"drainage_factor": 1.0, "absorption_factor": 1.0, "name": "Dat pha"},
    "clay": {"drainage_factor": 0.5, "absorption_factor": 0.6, "name": "Dat set"},
}

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

# ============================================================
# PID Controller Parameters
#
# QUAN TRONG: PID dung dt_real (thoi gian thuc, tinh bang giay).
# KHONG nhan TIME_SCALE vi setpoint va error la gia tri do am (%),
# khong phai gia tri trong khong gian thoi gian.
# Nhan TIME_SCALE = 10 se lam KI & KD lech 10 lan.
#
# Tuning (Heuristics, plant vat ly mo phong):
#   KP=2.0: du manh de keo am len, khong gay dao dong
#   KI=0.1: tich luy cham, xoa sai so xac lap
#   KD=0.5: giam chan, chong vot lo (overshoot)
#   LPF alpha=0.3: loc nhieu spike tren derivative term
# ============================================================
PID_ENABLED: bool      = True
PID_KP: float          = 2.0
PID_KI: float          = 0.1
PID_KD: float          = 0.5
PID_INTEGRAL_MAX: float = 50.0
PID_OUTPUT_MIN: float   = 0.0
PID_OUTPUT_MAX: float   = 100.0
PID_DEADBAND: float     = 2.0   # Vung chet: sai so < 2% -> khong thay doi output

# Safety guard
MAX_PUMP_DURATION_SEC = 300  # Toi da 5 phut tuoi lien tuc

DB_PATH          = "dulieu_nhakinh.db"
DB_MAX_RECORDS   = 10000
DB_CLEANUP_BATCH = 1000

ALERT_COOLDOWN    = 300
ALERT_MAX_HISTORY = 200

# ============================================================
# Scheduler intervals (giay)
# TASK_INTERVAL_MQTT = RATE_LIMIT_MIN_INTERVAL de dong bo
# ============================================================
SCHEDULER_TICK             = 0.1
TASK_INTERVAL_ENVIRONMENT  = 5
TASK_INTERVAL_PUMP         = 3
TASK_INTERVAL_MQTT         = 22   # = RATE_LIMIT_MIN_INTERVAL
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
        
    # FIX Bug An (Config Validation): Kiem tra kieu du lieu nghiem ngat tai runtime (giong Pydantic)
    current_module = sys.modules[__name__]
    annotations = getattr(current_module, "__annotations__", {})
    for var_name, expected_type in annotations.items():
        actual_val = getattr(current_module, var_name, None)
        if actual_val is not None:
            # Cho phep truyen int vao float
            if expected_type is float and isinstance(actual_val, int):
                continue
            if not isinstance(actual_val, expected_type):
                errors.append(f"Loi Kieu Du Lieu (Type Error): '{var_name}' phai la {expected_type.__name__}, nhung hien tai la {type(actual_val).__name__} ({repr(actual_val)})")
                
    return errors


_validation_errors = validate()
if _validation_errors:
    import logging as _log
    for err in _validation_errors:
        _log.warning(f"[CONFIG] {err}")
