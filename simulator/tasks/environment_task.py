"""
Nha Kinh Thong Minh - Task Mo Phong Moi Truong
=================================================
NANG CAP v3.0:
  [1] Magnus formula chinh xac cho Dew Point
  [2] Leaf Transpiration model (Penman-Monteith simplified)
  [3] Gaussian spike model linh hoat (sigma tu config)
  [4] Thermal inertia dung dt_factor (alpha = INERTIA^dt_factor)
  [5] Su kien thoi tiet ket thuc dua tren sim_minutes tuyet doi
"""

import math
import random
import time
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.env")

# ---------- Magnus formula constants (Lawrence 2005) ----------
_MAGNUS_A = 17.625
_MAGNUS_B = 243.04  # deg C

def _rh_from_dewpoint(temp_c: float, dew_c: float) -> float:
    """Tinh do am tuong doi tu nhiet do va diem suong (Magnus inverse)."""
    num = math.exp((_MAGNUS_A * dew_c) / (_MAGNUS_B + dew_c))
    den = math.exp((_MAGNUS_A * temp_c) / (_MAGNUS_B + temp_c))
    return max(20.0, min(100.0, 100.0 * num / den))


class EnvironmentTask(BaseTask):
    """Task mo phong moi truong nha kinh."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config     = config
        self.run_count  = 0
        self._last_time = time.time()
        self._transpiration_acc = 0.0
        self._weather_cooldown_end = 0.0  # Khởi tạo rõ ràng thay vì tạo động


        # Spike model (sigma tu config, khong hardcode)
        self._spike_prob  = getattr(config, 'SENSOR_SPIKE_PROB',  0.02)
        self._spike_sigma = getattr(config, 'SENSOR_SPIKE_SIGMA', 2.0)

        soil_type  = getattr(config, 'SOIL_TYPE', 'loam')
        soil_props = getattr(config, 'SOIL_PROPERTIES', {})
        self._soil = soil_props.get(
            soil_type,
            {"drainage_factor": 1.0, "absorption_factor": 1.0, "name": "Dat pha"}
        )
        logger.info(
            f"  [SOIL] Loai dat: {self._soil['name']} "
            f"(drainage={self._soil['drainage_factor']}, "
            f"absorption={self._soil['absorption_factor']})"
        )

    def shutdown(self) -> None:
        pass

    def run(self):
        cfg      = self.config
        gh       = self.greenhouse

        gh.update_sim_time()
        sim_hour = gh.get_sim_hour_float()
        is_day   = gh.is_daytime()
        weather  = gh.get_weather()

        self._check_weather_events(weather)
        weather = gh.get_weather()

        light = self._calc_light(sim_hour, is_day, weather)

        now     = time.time()
        dt_real = now - self._last_time
        self._last_time = now
        
        # FIX: Neu dt_real vuot qua nguong (do OS Sleep), ta clamp va canh bao
        if dt_real > cfg.TASK_INTERVAL_ENVIRONMENT * 3:
            logger.warning(f"  [ENV] Phat hien OS Sleep hoac Block (dt_real={dt_real:.1f}s). Clamping de bao ve logic vat ly.")
            dt_real = cfg.TASK_INTERVAL_ENVIRONMENT * 3
            
        dt_real   = max(0.01, min(dt_real, cfg.TASK_INTERVAL_ENVIRONMENT * 3))
        dt_factor = dt_real / cfg.TASK_INTERVAL_ENVIRONMENT

        temperature = self._calc_temperature(sim_hour, is_day, weather, light, dt_factor)
        moisture    = self._calc_moisture(is_day, weather, dt_factor, light, temperature)
        humidity    = self._calc_humidity_magnus(is_day, weather, temperature, moisture)
        co2         = self._calc_co2(sim_hour, is_day, light, temperature, dt_factor, weather)

        gh.set_sensors(
            temperature=temperature,
            light_intensity=light,
            soil_moisture=moisture,
            humidity=humidity,
            co2_level=co2,
        )

        self.run_count += 1
        day_str  = "[NGAY]" if is_day else "[DEM] "
        w_str    = f" [{weather['condition'].upper()}]" if weather["condition"] != "clear" else ""
        sim_time = gh.get_sim_time_str()
        logger.info(
            f"[{sim_time}] {day_str}{w_str} | "
            f"M={moisture:.1f}% T={temperature:.1f}C "
            f"L={light:.0f}lux H={humidity:.1f}% "
            f"CO2={co2:.0f}ppm | "
            f"Pump={'ON' if gh.is_pump_on() else 'OFF'}"
        )

    def _check_weather_events(self, weather):
        cfg         = self.config
        gh          = self.greenhouse
        now_minutes = gh.get_sim_minutes_absolute()

        if weather["condition"] != "clear":
            end_minutes = gh.get_weather_event_end_minutes()
            if now_minutes >= end_minutes:
                gh.set_weather("clear", 0, 0, 0)
                # FIX: Them thoi gian cooldown sau khi ket thuc su kien thoi tiet (Mac dinh: 120 phut sim)
                cooldown_minutes = getattr(cfg, 'WEATHER_COOLDOWN_MINUTES', 120.0)
                self._weather_cooldown_end = now_minutes + cooldown_minutes
                logger.info(f"  [THOI TIET] Troi quang dang (vao thoi gian nghi {cooldown_minutes} phut sim)")
            return

        # FIX: Kiem tra thoi gian cooldown (neu co) truoc khi cho phep random su kien tiep
        if now_minutes < self._weather_cooldown_end:
            return

        if random.random() < cfg.WEATHER_EVENT_CHANCE:
            if random.random() < 0.4:
                duration_minutes = cfg.WEATHER_RAIN_DURATION * 60
                intensity        = random.uniform(0.3, 0.9)
                gh.set_weather("rainy", 0.8, intensity, now_minutes + duration_minutes)
                logger.info(f"  [THOI TIET] Bat dau mua (cuong do: {intensity:.1f})")
            else:
                duration_minutes = cfg.WEATHER_CLOUD_DURATION * 60
                cover            = random.uniform(0.3, 0.7)
                gh.set_weather("cloudy", cover, 0, now_minutes + duration_minutes)
                logger.info(f"  [THOI TIET] Troi am u (may: {cover:.0%})")

    def _calc_temperature(self, sim_hour, is_day, weather, light, dt_factor):
        """
        Mo hinh nhiet do + Thermal Inertia dung dt_factor.
        NANG CAP: alpha = THERMAL_INERTIA^dt_factor
                  Dam bao vat ly dung ca khi task bi delay.
        """
        cfg = self.config

        base     = (cfg.TEMP_DAY_BASE + cfg.TEMP_NIGHT_BASE) / 2
        amp      = (cfg.TEMP_DAY_BASE - cfg.TEMP_NIGHT_BASE) / 2
        raw_temp = base + amp * math.sin((sim_hour - 8) * math.pi / 12)

        if weather["condition"] == "cloudy":
            raw_temp -= 2.0 * weather["cloud_cover"]
        elif weather["condition"] == "rainy":
            raw_temp -= 4.0 * weather["rain_intensity"]

        if is_day and light > 0:
            raw_temp += (light / cfg.LIGHT_DAY_MAX) * 3.0

        raw_temp += random.gauss(0, cfg.TEMP_NOISE)

        # Gaussian spike model (sigma tu config)
        if random.random() < self._spike_prob:
            raw_temp += random.gauss(0, self._spike_sigma) * random.choice([-1, 1])

        # Thermal inertia: alpha = INERTIA^dt_factor (dung vat ly)
        # FIX: Doc truc tiep gh.temperature de khong bi mat precision do ham get_sensors lam tron (Quantization Error)
        prev  = self.greenhouse.temperature
        alpha = cfg.THERMAL_INERTIA ** dt_factor
        temp  = prev * alpha + raw_temp * (1.0 - alpha)

        return max(5.0, min(50.0, temp))

    def _calc_light(self, sim_hour, is_day, weather):
        cfg = self.config
        if not is_day:
            return cfg.LIGHT_NIGHT_MAX + random.uniform(0, 5)

        hour_from_noon = abs(sim_hour - 12)
        ratio = max(0, 1 - (hour_from_noon / 6) ** 2)
        light = cfg.LIGHT_DAY_MAX * ratio

        if weather["condition"] == "cloudy":
            light *= (1 - weather["cloud_cover"] * 0.6)
        elif weather["condition"] == "rainy":
            light *= 0.2

        light += random.gauss(0, cfg.LIGHT_NOISE)
        return max(0, light)

    def _calc_moisture(self, is_day, weather, dt_factor, light, temperature):
        """
        Tinh do am dat voi Leaf Transpiration model.
        NANG CAP: Penman-Monteith simplified (anh sang + nhiet do)
        """
        cfg      = self.config
        # FIX: Doc truc tiep gh.soil_moisture de tranh Quantization Error tu get_sensors lam tron
        moisture = self.greenhouse.soil_moisture
        soil     = self._soil

        # 1. Bay hoi tu nhien
        decay = cfg.MOISTURE_DECAY_DAY if is_day else cfg.MOISTURE_DECAY_NIGHT
        moisture -= decay * dt_factor * soil["drainage_factor"]

        # 2. Thoat hoi nuoc la cay (Leaf Transpiration - Penman-Monteith simplified)
        if is_day and light > 0:
            transpiration_rate = (
                (light / cfg.LIGHT_DAY_MAX) * 0.05
                + max(0.0, (temperature - 20.0) / 100.0)
            )
            transpiration = transpiration_rate * dt_factor * soil["drainage_factor"]
            moisture -= transpiration
            self._transpiration_acc += transpiration

        # 3. Bom tuoi
        if self.greenhouse.is_pump_on():
            mode = self.greenhouse.get_mode()
            duty = (self.greenhouse.get_pump_duty()
                    if (mode == "AUTO" and self.config.PID_ENABLED)
                    else 100.0)
            moisture += cfg.MOISTURE_PUMP_RATE * (duty / 100.0) * dt_factor * soil["absorption_factor"]

        # 4. Mua
        if weather["condition"] == "rainy":
            moisture += (cfg.MOISTURE_RAIN_RATE
                         * weather["rain_intensity"]
                         * dt_factor
                         * soil["absorption_factor"])

        moisture += random.gauss(0, 0.2)
        return max(cfg.MOISTURE_MIN_CLAMP, min(cfg.MOISTURE_MAX_CLAMP, moisture))

    def _calc_humidity_magnus(self, is_day, weather, temperature, soil_moisture):
        """
        Tinh do am khong khi bang Magnus formula.
        NANG CAP:
          - Dew Point model chinh xac (thay the phuong trinh tuyen tinh)
          - Transpiration effect: do am dat <-> do am KK
          - Spike model cho cam bien DHT
        """
        cfg = self.config

        # Dew point co so (subtropical greenhouse, ban ngay/dem)
        base_dew = 15.0 if is_day else 18.0

        # Hieu ung thoi tiet
        if weather["condition"] == "rainy":
            base_dew += 5.0 * weather["rain_intensity"]
        elif weather["condition"] == "cloudy":
            base_dew += 2.0 * weather["cloud_cover"]

        # Transpiration: do am dat cao -> la cay boc hoi -> tang dew point
        transpiration_boost = (max(0.0, soil_moisture - 30.0) / 70.0) * 3.0
        base_dew += transpiration_boost

        # Noise cam bien DHT (±0.5 deg C)
        base_dew += random.gauss(0, 0.5)

        # Spike model
        if random.random() < self._spike_prob:
            base_dew += random.gauss(0, 1.5) * random.choice([-1, 1])

        # Magnus formula: tinh RH tu Dew Point
        rh = _rh_from_dewpoint(temperature, base_dew)
        rh += random.gauss(0, cfg.HUMIDITY_NOISE)
        return max(20.0, min(99.0, rh))

    def _calc_co2(self, sim_hour, is_day, light, temperature, dt_factor, weather):
        cfg     = self.config
        # FIX: Doc truc tiep gh.co2_level de tranh Quantization Error
        co2     = self.greenhouse.co2_level

        if is_day and light > 0:
            drop_rate = (light / cfg.LIGHT_DAY_MAX) * 12.0 * dt_factor
            co2 -= drop_rate
            co2  = max(250.0, co2)
        else:
            # FIX: CO2 ban dem phu thuoc vao nhiet do moi truong on dinh, khong bi giam dot ngot do nhiet do hien tai (mua lam mat)
            # Vi sinh vat hoat dong tang khi troi mua ban dem
            base_t = (cfg.TEMP_DAY_BASE + cfg.TEMP_NIGHT_BASE) / 2.0
            rise_rate = (base_t / 20.0) * 4.0 * dt_factor
            
            if not is_day and weather["condition"] == "rainy":
                rise_rate += 3.0 * dt_factor * weather["rain_intensity"]
                
            co2 += rise_rate
            co2  = min(cfg.CO2_MAX, co2)

        co2 += random.gauss(0, cfg.CO2_NOISE)

        if random.random() < self._spike_prob:
            co2 += random.gauss(0, 40.0) * random.choice([-1, 1])

        return max(200.0, min(2000.0, co2))
