"""
Nha Kinh Thong Minh - Task Mo Phong Moi Truong
=================================================
Mo phong cam bien: nhiet do (sin ngay/dem), anh sang,
do am dat (suy giam tu nhien), do am KK, CO2,
su kien thoi tiet (mua/may), thermal inertia.

FIX: Su kien thoi tiet ket thuc dua tren sim_minutes tuyet doi
     (khong con loi stuck khi qua moc 24h mo phong)
"""

import math
import random
import logging

logger = logging.getLogger("task.env")


class EnvironmentTask:
    """Task mo phong moi truong nha kinh."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config     = config
        self.run_count  = 0

    def run(self):
        cfg     = self.config
        gh      = self.greenhouse

        gh.update_sim_time()
        sim_hour = gh.get_sim_hour_float()
        is_day   = gh.is_daytime()
        weather  = gh.get_weather()

        # --- Kiem tra su kien thoi tiet ---
        self._check_weather_events(weather)

        # Lay lai weather sau khi co the da cap nhat
        weather = gh.get_weather()

        # --- Nhiet do (mo hinh sin + thermal inertia) ---
        temperature = self._calc_temperature(sim_hour, is_day, weather)

        # --- Anh sang ---
        light = self._calc_light(sim_hour, is_day, weather)

        # --- Do am dat ---
        moisture = self._calc_moisture(is_day, weather)

        # --- Do am khong khi ---
        humidity = self._calc_humidity(sim_hour, is_day, weather)

        # --- CO2 ---
        co2 = self._calc_co2(sim_hour, is_day)

        # Cap nhat tat ca cam bien
        gh.set_sensors(
            temperature=temperature,
            light_intensity=light,
            soil_moisture=moisture,
            humidity=humidity,
            co2_level=co2,
            prev_temperature=temperature,
        )

        self.run_count += 1
        day_str = "[NGAY]" if is_day else "[DEM] "
        w_str   = f" [{weather['condition'].upper()}]" if weather["condition"] != "clear" else ""
        sim_time = gh.get_sim_time_str()
        logger.info(
            f"[{sim_time}] {day_str}{w_str} | "
            f"M={moisture:.1f}% T={temperature:.1f}C "
            f"L={light:.0f}lux H={humidity:.1f}% "
            f"CO2={co2:.0f}ppm | "
            f"Pump={'ON' if gh.is_pump_on() else 'OFF'}"
        )

    def _check_weather_events(self, weather):
        """
        Kiem tra va tao su kien thoi tiet.

        FIX: So sanh theo sim_minutes tuyet doi (khong mod 24h)
             Tranh bug: su kien bat luc 23h, end_time=25h,
             sang hom sau sim_hour=6 < 25 → khong bao gio ket thuc.
        """
        cfg = self.config
        gh  = self.greenhouse

        # Lay thoi diem hien tai theo phut tuyet doi
        now_minutes = gh.get_sim_minutes_absolute()

        # Neu dang co su kien, kiem tra het chua
        if weather["condition"] != "clear":
            end_minutes = gh.get_weather_event_end_minutes()
            if now_minutes >= end_minutes:
                gh.set_weather("clear", 0, 0, 0)
                logger.info("  [THOI TIET] Troi quang dang")
            return

        # Random su kien moi
        if random.random() < cfg.WEATHER_EVENT_CHANCE:
            if random.random() < 0.4:
                # Mua - tinh end_minutes tuyet doi
                duration_minutes = cfg.WEATHER_RAIN_DURATION * 60  # doi gio → phut mo phong
                intensity        = random.uniform(0.3, 0.9)
                gh.set_weather(
                    "rainy", 0.8, intensity,
                    now_minutes + duration_minutes,
                )
                logger.info(f"  [THOI TIET] Bat dau mua (cuong do: {intensity:.1f})")
            else:
                # May
                duration_minutes = cfg.WEATHER_CLOUD_DURATION * 60
                cover            = random.uniform(0.3, 0.7)
                gh.set_weather(
                    "cloudy", cover, 0,
                    now_minutes + duration_minutes,
                )
                logger.info(f"  [THOI TIET] Troi am u (may: {cover:.0%})")

    def _calc_temperature(self, sim_hour, is_day, weather):
        """Tinh nhiet do theo mo hinh sin + thermal inertia."""
        cfg = self.config

        base    = (cfg.TEMP_DAY_BASE + cfg.TEMP_NIGHT_BASE) / 2
        amp     = (cfg.TEMP_DAY_BASE - cfg.TEMP_NIGHT_BASE) / 2
        raw_temp = base + amp * math.sin((sim_hour - 8) * math.pi / 12)

        if weather["condition"] == "cloudy":
            raw_temp -= 2.0 * weather["cloud_cover"]
        elif weather["condition"] == "rainy":
            raw_temp -= 4.0 * weather["rain_intensity"]

        raw_temp += random.gauss(0, cfg.TEMP_NOISE)

        prev        = self.greenhouse.prev_temperature
        inertia     = cfg.THERMAL_INERTIA
        temperature = prev * inertia + raw_temp * (1 - inertia)

        return max(5.0, min(50.0, temperature))

    def _calc_light(self, sim_hour, is_day, weather):
        """Tinh cuong do anh sang."""
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

    def _calc_moisture(self, is_day, weather):
        """Tinh do am dat."""
        cfg     = self.config
        sensors = self.greenhouse.get_sensors()
        moisture = sensors["soil_moisture"]

        if is_day:
            moisture -= cfg.MOISTURE_DECAY_DAY
        else:
            moisture -= cfg.MOISTURE_DECAY_NIGHT

        if self.greenhouse.is_pump_on():
            moisture += cfg.MOISTURE_PUMP_RATE

        if weather["condition"] == "rainy":
            moisture += cfg.MOISTURE_RAIN_RATE * weather["rain_intensity"]

        moisture += random.gauss(0, 0.2)
        return max(cfg.MOISTURE_MIN_CLAMP, min(cfg.MOISTURE_MAX_CLAMP, moisture))

    def _calc_humidity(self, sim_hour, is_day, weather):
        """Tinh do am khong khi."""
        cfg = self.config

        base     = cfg.HUMIDITY_BASE
        amp      = cfg.HUMIDITY_AMPLITUDE
        humidity = base + amp * math.sin((sim_hour - 2) * math.pi / 12)

        if weather["condition"] == "rainy":
            humidity += 15 * weather["rain_intensity"]
        elif weather["condition"] == "cloudy":
            humidity += 5 * weather["cloud_cover"]

        humidity += random.gauss(0, cfg.HUMIDITY_NOISE)
        return max(20.0, min(99.0, humidity))

    def _calc_co2(self, sim_hour, is_day):
        """Tinh nong do CO2."""
        cfg = self.config

        if is_day:
            co2 = cfg.CO2_BASE - cfg.CO2_DAY_DROP * math.sin(
                (sim_hour - 6) * math.pi / 12
            )
        else:
            co2 = cfg.CO2_BASE + cfg.CO2_NIGHT_RISE * 0.5

        co2 += random.gauss(0, cfg.CO2_NOISE)
        return max(200, min(2000, co2))
