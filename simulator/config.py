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
FEED_SOIL_MOISTURE  = "soil-moisture"   # DEPRECATED: giu lai de tuong thich LWT
FEED_TEMPERATURE    = "temperature"     # DEPRECATED: giu lai de backward compat
FEED_LIGHT          = "light-intensity" # DEPRECATED
FEED_HUMIDITY       = "humidity"        # DEPRECATED
FEED_CO2            = "co2-level"       # DEPRECATED
FEED_PUMP_STATUS    = "pump-status"     # Van dung cho LWT
FEED_PUMP_CMD       = "pump-cmd"
FEED_MODE           = "greenhouse-mode"
FEED_THRESHOLD      = "moisture-threshold"
FEED_AI_STATUS      = "ai-status"
FEED_AI_CMD         = "ai-command"
FEED_WATERING_EVENT = "watering-event"
FEED_ALERT          = "alert-status"

# NANG CAP v5.0: Batch publish - gom tat ca sensor vao 1 JSON
# Tiet kiem: 9 feeds/cycle -> 2 feeds/cycle (sensor-data + ai-status)
# Con lai 28 points/phut cho alerts va events
FEED_SENSOR_DATA    = "sensor-data"

def get_topic(feed_name):
    return f"{ADAFRUIT_USERNAME}/feeds/{feed_name}"

# ============================================================
# Rate Limiter (Adafruit IO Free: 30 data points / phut)
# NANG CAP v5.0: Batch publish
#   Truoc: 9 feeds x (60/22s) = ~24.5/phut (chat, chi con 5.5 cho alerts)
#   Sau:   2 feeds (sensor-data + ai-status) x (60/5s) = ~24/phut
#          Con lai ~6 points/phut cho alerts va events
#   Burst guard 1.5s van giu -> thuc te safe hon ly thuyet
# ============================================================
RATE_LIMIT_POINTS_PER_MIN    = 30
RATE_LIMIT_FEEDS_PER_PUBLISH = 2   # sensor-data + ai-status
RATE_LIMIT_MIN_INTERVAL      = 5   # 2 feeds x 12/phut = 24/phut < 30

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

# ============================================================
# EC Model (Electrical Conductivity - do dan dien, mS/cm)
#
# Nguyen ly vat ly:
#   - Tuoi nuoc -> pha loang muoi -> EC giam (dilution effect)
#   - Bay hoi nuoc ban ngay -> muoi tap trung -> EC tang cham (concentration)
#   - Mua -> EC giam nhanh (nuoc mua ~distilled, EC ~ 0)
#   - Nhiet do cao -> EC do cao hon (2%/degC, chuan IEC 60746-3)
#   - Phan bon -> EC tang theo thoi gian (simulation: tang rat cham)
#
# Range thuc te:
#   Toi uu rau an la:  1.5 - 2.5 mS/cm
#   Canh bao thap:     < 1.0 mS/cm  (thieu dinh duong)
#   Canh bao cao:      > 3.0 mS/cm  (mat nuoc, cay stress)
#   Nguy hiem:         > 3.5 mS/cm  (doc muoi)
# ============================================================
EC_INIT: float          = 2.0    # mS/cm khoi dong
EC_MIN_CLAMP: float     = 0.3    # mS/cm thap nhat co the
EC_MAX_CLAMP: float     = 4.5    # mS/cm cao nhat co the
EC_OPT_LOW: float       = 1.5    # nguong toi uu (duoi)
EC_OPT_HIGH: float      = 2.5    # nguong toi uu (tren)
EC_WARN_LOW: float      = 1.0    # canh bao thieu dinh duong
EC_WARN_HIGH: float     = 3.0    # canh bao mat nuoc / muoi
EC_NOISE: float         = 0.05   # Gaussian noise cam bien (mS/cm)

# Toc do thay doi EC (%/dt_factor, tinh tren EC hien tai)
EC_DILUTION_RATE: float     = 0.04   # Giam % EC moi tick khi bom chay
EC_CONCENTRATION_RATE: float = 0.003  # Tang % EC moi tick do bay hoi ban ngay
EC_RAIN_DILUTION: float     = 0.08   # Giam % EC moi tick khi mua
EC_FERTILIZER_RATE: float   = 0.0005 # Tang tuyet doi mS/cm moi tick (phan bon nen)
EC_TEMP_COEFF: float        = 0.02   # 2%/degC, chuan IEC (ap dung khi hien thi)

# ============================================================
# pH Model
#
# Nguyen ly hoa hoc:
#   - CO2 hoa tan vao nuoc -> H2CO3 (acid carbonic) -> giam pH
#     pH = pKa1 - log([CO2]/[HCO3-]) ~ 8.3 - 0.008*CO2_ppm (linearized)
#   - Tuoi nuoc -> pH drift ve trung tinh (7.0), pha loang acid/base
#   - Mua acid nhe (pH mua ~ 5.6 o do thi) -> ha pH dat / dung dich
#   - Phan bon ammonium (NH4+) -> nito hoa -> H+ -> giam pH theo thoi gian
#   - Vi sinh vat hoat dong dem -> tiet acid huu co -> pH giam nhe
#
# Range thuc te:
#   Toi uu hau het cay trong: 6.0 - 6.8
#   Canh bao acid:   < 5.8  (khoa dinh duong sat, mangan)
#   Canh bao kieu:   > 7.2  (khoa sat, keo, bo, mangan)
#   Nguy hiem:       < 5.5 hoac > 7.5
# ============================================================
PH_INIT: float          = 6.5    # pH khoi dong
PH_MIN_CLAMP: float     = 4.5    # pH thap nhat (cham du an toan)
PH_MAX_CLAMP: float     = 8.5    # pH cao nhat
PH_OPT_LOW: float       = 6.0    # nguong toi uu (duoi)
PH_OPT_HIGH: float      = 6.8    # nguong toi uu (tren)
PH_WARN_LOW: float      = 5.8    # canh bao acid
PH_WARN_HIGH: float     = 7.2    # canh bao kiem
PH_NOISE: float         = 0.03   # Gaussian noise cam bien pH

# Cac he so mo hinh pH
PH_CO2_SENSITIVITY: float   = 0.003  # DeltapH moi ppm CO2 vuot nguong 400ppm
PH_CO2_BASELINE: float      = 400.0  # ppm CO2 tham chieu (pH baseline)
PH_IRRIGATION_DRIFT: float  = 0.008  # Toc do pH drift ve 7.0 khi tuoi (moi tick)
PH_RAIN_EFFECT: float       = 0.05   # pH giam moi tick khi mua (acid)
PH_MICROBIAL_NIGHT: float   = 0.002  # pH giam ban dem (vi sinh vat + CO2 dat)
PH_FERTILIZER_ACIDIFY: float = 0.0003 # pH giam rat cham do phan bon ammonium
PH_EQUILIBRIUM: float       = 6.8    # pH can bang tu nhien dat nha kinh

# ============================================================
# Crop Model — FAO-56 Kc + Water Stress Index (WSI)
#
# Ly thuyet (FAO Irrigation & Drainage Paper 56):
#   Kc (Crop Coefficient): ti so giua ET cay trong va ET tham chieu
#   Thay doi theo 4 giai doan sinh truong:
#     Initial -> Development -> Mid-season -> Late-season
#
#   WSI (Water Stress Index, tu AquaCrop simplified):
#     WSI = 0: du nuoc, stomata mo toi da
#     WSI = 1: heo, stomata dong, khong thoat hoi nuoc
#     Ks = 1 - WSI: he so stress ap dung len Kc
#
# Tham khao: Allen et al. 1998, FAO-56 Table 11, 12, 22
# ============================================================
CROP_TOTAL_DAYS: int = 90      # Tong chu ky sinh truong (ngay mo phong)

# Phan chia giai doan (% tong ngay, FAO-56 Table 11 - rau an la nhiet doi)
CROP_PCT_INITIAL: float      = 0.20   # 20% dau: cay con
CROP_PCT_DEVELOPMENT: float  = 0.30   # 30% tiep: phat trien
CROP_PCT_MID: float          = 0.30   # 30% tiep: truong thanh
# Cuoi mua = 1 - 0.20 - 0.30 - 0.30 = 0.20 (tu dong)

# He so Kc (FAO-56 Table 12, rau an la / salad crops)
CROP_KC_INI: float = 0.40   # Kc giai doan dau (mat dat thoang)
CROP_KC_MID: float = 1.05   # Kc giua mua (thoat hoi nuoc max)
CROP_KC_END: float = 0.55   # Kc cuoi mua (la rung, thu hoach)

# Nguong do am dat (FAO AquaCrop)
CROP_THETA_FC: float      = 65.0   # Field Capacity - suc chua dong ruong (%)
CROP_THETA_WP: float      = 15.0   # Wilting Point - diem heo (%)
CROP_P_DEPLETION: float   = 0.55   # Muc kiet nuoc cho phep truoc khi stress
                                    # (p=0.55 cho rau, FAO-56 Table 22)

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
TASK_INTERVAL_MQTT         = 5    # = RATE_LIMIT_MIN_INTERVAL (batch: 2 feeds/cycle)
TASK_INTERVAL_AI           = 30
TASK_INTERVAL_ALERT        = 5
TASK_INTERVAL_PERSISTENCE  = 30

WATCHDOG_ENABLED = True
WATCHDOG_TIMEOUT = 10.0

# ============================================================
# REST API + WebSocket Server (nang cap v4.0)
# Thay the HealthCheckTask bang APIServerTask
# Dashboard co the hoat dong OFFLINE hoan toan qua local API
# ============================================================
API_PORT              = 8080   # Port cho FastAPI + WebSocket
WS_BROADCAST_INTERVAL = 2.0    # Push WebSocket moi N giay


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
