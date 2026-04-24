"""
Nha Kinh Thong Minh - Task Canh Bao
=====================================
Giam sat nguong cam bien va phat canh bao.
3 muc: INFO, WARNING, CRITICAL. Co cooldown.
"""

import time
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.alert")


class AlertTask(BaseTask):
    """Task giam sat va phat canh bao."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self._cooldowns = {}
        
        # Buffer for Trend & Z-score detection
        self.HISTORY_MAX = 60
        self._history = {
            "soil_moisture": [],
            "temperature": []
        }

    def shutdown(self) -> None:
        """Khong co tai nguyen can giai phong."""
        pass

    def run(self):
        cfg = self.config
        sensors = self.greenhouse.get_sensors()
        now = time.time()
        
        # Update rolling history for analytics
        for key in ["soil_moisture", "temperature"]:
            self._history[key].append(sensors[key])
            if len(self._history[key]) > self.HISTORY_MAX:
                self._history[key].pop(0)

        checks = [
            ("MOISTURE_LOW", 15 <= sensors["soil_moisture"] < cfg.MOISTURE_LOW,
             f"Do am dat thap: {sensors['soil_moisture']:.1f}%", "WARNING"),

            ("MOISTURE_CRITICAL", sensors["soil_moisture"] < 15,
             f"Do am dat RAT THAP: {sensors['soil_moisture']:.1f}%!", "CRITICAL"),

            ("MOISTURE_HIGH", sensors["soil_moisture"] > 85,
             f"Do am dat qua cao: {sensors['soil_moisture']:.1f}%", "WARNING"),

            ("TEMP_HIGH", sensors["temperature"] > cfg.TEMP_MAX,
             f"Nhiet do qua cao: {sensors['temperature']:.1f}C!", "CRITICAL"),

            ("TEMP_LOW", sensors["temperature"] < cfg.TEMP_MIN,
             f"Nhiet do qua thap: {sensors['temperature']:.1f}C", "WARNING"),

            ("HUMIDITY_LOW", sensors["humidity"] < cfg.HUMIDITY_MIN,
             f"Do am KK thap: {sensors['humidity']:.1f}%", "WARNING"),

            ("HUMIDITY_HIGH", sensors["humidity"] > cfg.HUMIDITY_MAX,
             f"Do am KK cao: {sensors['humidity']:.1f}%", "WARNING"),

            ("CO2_HIGH", sensors["co2_level"] > cfg.CO2_MAX,
             f"CO2 vuot nguong: {sensors['co2_level']:.0f}ppm!", "WARNING"),

            # --- EC alerts (v6.0) ---
            ("EC_LOW", sensors["ec_level"] < cfg.EC_WARN_LOW,
             f"EC thap - thieu dinh duong: {sensors['ec_level']:.2f} mS/cm", "WARNING"),

            ("EC_HIGH", sensors["ec_level"] > cfg.EC_WARN_HIGH,
             f"EC cao - nguy co mat nuoc / muoi: {sensors['ec_level']:.2f} mS/cm", "WARNING"),

            ("EC_CRITICAL", sensors["ec_level"] > cfg.EC_MAX_CLAMP * 0.85,
             f"EC NGUY HIEM - doc muoi: {sensors['ec_level']:.2f} mS/cm!", "CRITICAL"),

            # --- pH alerts (v6.0) ---
            ("PH_LOW", sensors["ph_level"] < cfg.PH_WARN_LOW,
             f"pH dat qua acid: {sensors['ph_level']:.2f} (toi uu: {cfg.PH_OPT_LOW}-{cfg.PH_OPT_HIGH})", "WARNING"),

            ("PH_HIGH", sensors["ph_level"] > cfg.PH_WARN_HIGH,
             f"pH dat qua kiem: {sensors['ph_level']:.2f} (toi uu: {cfg.PH_OPT_LOW}-{cfg.PH_OPT_HIGH})", "WARNING"),

            ("PH_CRITICAL_LOW", sensors["ph_level"] < cfg.PH_MIN_CLAMP + 0.5,
             f"pH NGUY HIEM - acid nang: {sensors['ph_level']:.2f}!", "CRITICAL"),
        ]

        # ---------------------------------------------------------
        # AI ALERT ENGINE: Trend Detection + Anomaly Z-Score
        # ---------------------------------------------------------
        hist_m = self._history["soil_moisture"]
        if len(hist_m) >= 20:
            # Tốc độ thay đổi (%/phút) - Giả sử 1 tick ~ 1 giây mô phỏng
            rate_m = ((hist_m[-1] - hist_m[0]) / len(hist_m)) * 60
            if rate_m <= -2.0:
                checks.append(("MOISTURE_LEAK_TREND", True,
                 f"Độ ẩm đang giảm {abs(rate_m):.1f}%/phút — Cảnh báo đất không giữ được nước hoặc rò rỉ!", "CRITICAL"))

            mean_m = sum(hist_m) / len(hist_m)
            std_m = (sum((x - mean_m)**2 for x in hist_m) / len(hist_m)) ** 0.5
            if std_m > 0.05:
                z_m = (sensors["soil_moisture"] - mean_m) / std_m
                if z_m < -3.0:
                    checks.append(("MOISTURE_ANOMALY_ZSCORE", True,
                     f"Bất thường độ ẩm (Z-score: {z_m:.1f}) — Suy giảm đột biến ngoài dự đoán thống kê!", "WARNING"))

        hist_t = self._history["temperature"]
        if len(hist_t) >= 20:
            rate_t = ((hist_t[-1] - hist_t[0]) / len(hist_t)) * 60
            if rate_t >= 3.0:
                checks.append(("TEMP_SPIKE_TREND", True,
                 f"Nhiệt độ đang tăng {rate_t:.1f}°C/phút — Kiểm tra hệ thống thông gió hoặc tản nhiệt ngay!", "CRITICAL"))

            mean_t = sum(hist_t) / len(hist_t)
            std_t = (sum((x - mean_t)**2 for x in hist_t) / len(hist_t)) ** 0.5
            if std_t > 0.05:
                z_t = (sensors["temperature"] - mean_t) / std_t
                if z_t > 3.0:
                    checks.append(("TEMP_ANOMALY_ZSCORE", True,
                     f"Bất thường nhiệt độ (Z-score: {z_t:.1f}) — Tăng vọt bất thường!", "WARNING"))

        for alert_type, condition, message, severity in checks:
            if not condition:
                continue

            # Kiem tra cooldown
            last = self._cooldowns.get(alert_type, 0)
            if (now - last) < cfg.ALERT_COOLDOWN:
                continue

            self._cooldowns[alert_type] = now
            self.greenhouse.add_alert(alert_type, message, severity)
            logger.warning(f"  [CANH BAO] [{severity}] {message}")
