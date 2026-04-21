"""
Nha Kinh Thong Minh - Task Canh Bao
=====================================
Giam sat nguong cam bien va phat canh bao.
3 muc: INFO, WARNING, CRITICAL. Co cooldown.
"""

import time
import logging

logger = logging.getLogger("task.alert")


class AlertTask:
    """Task giam sat va phat canh bao."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self._cooldowns = {}

    def run(self):
        cfg = self.config
        sensors = self.greenhouse.get_sensors()
        now = time.time()

        checks = [
            ("MOISTURE_LOW", sensors["soil_moisture"] < cfg.MOISTURE_LOW,
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
        ]

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
