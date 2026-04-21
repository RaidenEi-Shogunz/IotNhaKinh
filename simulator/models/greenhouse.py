"""
Nha Kinh Thong Minh - Mo hinh du lieu nha kinh
================================================
Thread-safe shared state cho tat ca cac task.

CHANGES:
  - Them add_pump_runtime() de PumpTask khoi vi pham encapsulation
  - _lock giu la private, khong truy cap tu ben ngoai
"""

import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any


class BanGhiTuoi:
    """Mot ban ghi tuoi nuoc."""
    def __init__(self, action, moisture, sim_time_str, trigger):
        self.action     = action
        self.moisture   = moisture
        self.sim_time   = sim_time_str
        self.real_time  = datetime.now().strftime("%H:%M:%S")
        self.trigger    = trigger

    def to_dict(self):
        return {
            "action":    self.action,
            "moisture":  round(self.moisture, 1),
            "sim_time":  self.sim_time,
            "real_time": self.real_time,
            "trigger":   self.trigger,
        }


class BanGhiCanhBao:
    """Mot ban ghi canh bao."""
    def __init__(self, alert_type, message, severity, sim_time_str):
        self.alert_type   = alert_type
        self.message      = message
        self.severity     = severity
        self.sim_time     = sim_time_str
        self.real_time    = datetime.now().strftime("%H:%M:%S")
        self.acknowledged = False

    def to_dict(self):
        return {
            "type":         self.alert_type,
            "message":      self.message,
            "severity":     self.severity,
            "sim_time":     self.sim_time,
            "real_time":    self.real_time,
            "acknowledged": self.acknowledged,
        }


class TrangThaiPID:
    """Trang thai PID controller."""
    def __init__(self):
        self.error      = 0.0
        self.integral   = 0.0
        self.derivative = 0.0
        self.output     = 0.0
        self.setpoint   = 50.0

    def to_dict(self):
        return {
            "error":      round(self.error, 2),
            "integral":   round(self.integral, 2),
            "derivative": round(self.derivative, 2),
            "output":     round(self.output, 1),
            "setpoint":   round(self.setpoint, 1),
        }


class TrangThaiThoiTiet:
    """Trang thai thoi tiet."""
    def __init__(self):
        self.condition     = "clear"
        self.cloud_cover   = 0.0
        self.rain_intensity = 0.0
        # FIX: luu absolute sim_minutes thay vi sim_hour-trong-ngay
        self.event_end_minutes = 0.0

    def to_dict(self):
        return {
            "condition":      self.condition,
            "cloud_cover":    round(self.cloud_cover, 2),
            "rain_intensity": round(self.rain_intensity, 2),
        }


class Greenhouse:
    """
    Mo hinh trung tam cua nha kinh.
    Thread-safe: doc/ghi deu duoc bao ve boi Lock.
    """

    def __init__(self, config: Any) -> None:
        self._lock            = threading.Lock()
        self._config          = config
        self._start_real_time = time.time()
        self._sim_minutes     = config.DAY_START_HOUR * 60

        # Cam bien chinh
        self.soil_moisture  = config.MOISTURE_INIT
        self.temperature    = 25.0
        self.light_intensity = 0.0

        # Cam bien mo rong
        self.humidity          = 65.0
        self.co2_level         = 450.0
        self.prev_temperature  = 25.0

        # Bom
        self.pump_on          = False
        self.pump_duty_cycle  = 0.0
        self.total_water_used = 0.0
        self.pump_run_time    = 0.0

        # Che do
        self.mode              = "AUTO"
        self.moisture_threshold = config.MOISTURE_LOW

        # PID & Thoi tiet
        self.pid_state         = TrangThaiPID()
        self.pid_state.setpoint = config.MOISTURE_TARGET
        self.weather           = TrangThaiThoiTiet()

        # AI
        self.ai_status         = "Binh thuong"
        self.ai_confidence     = 0.0
        self.ai_recommendation = ""

        # Lich su
        self._watering_log   = []
        self._alert_history  = []

        # Thong ke
        self.total_pump_cycles = 0
        self.alerts_fired      = 0

    # ---------- Thoi gian mo phong ----------

    def update_sim_time(self):
        with self._lock:
            now   = time.time()
            delta = now - self._start_real_time
            self._sim_minutes = (
                self._config.DAY_START_HOUR * 60
                + (delta / 60.0) * self._config.TIME_SCALE
            )

    def get_sim_time(self) -> tuple[int, int]:
        with self._lock:
            total = self._sim_minutes % (24 * 60)
            return int(total // 60), int(total % 60)

    def get_sim_hour_float(self) -> float:
        with self._lock:
            return (self._sim_minutes % (24 * 60)) / 60.0

    def get_sim_minutes_absolute(self) -> float:
        """Tra ve tong so phut mo phong (khong mod 24h) - dung de tinh event end time."""
        with self._lock:
            return self._sim_minutes

    def get_sim_time_str(self) -> str:
        h, m = self.get_sim_time()
        return f"{h:02d}:{m:02d}"

    def is_daytime(self) -> bool:
        h = self.get_sim_hour_float()
        return self._config.DAY_START_HOUR <= h < self._config.DAY_END_HOUR

    def get_sim_day(self) -> int:
        with self._lock:
            return int(self._sim_minutes // (24 * 60)) + 1

    # ---------- Cam bien ----------

    def get_sensors(self):
        with self._lock:
            return {
                "soil_moisture":   round(self.soil_moisture, 1),
                "temperature":     round(self.temperature, 1),
                "light_intensity": round(self.light_intensity, 0),
                "humidity":        round(self.humidity, 1),
                "co2_level":       round(self.co2_level, 0),
            }

    # Whitelist cac truong cam bien duoc phep cap nhat qua set_sensors()
    _SENSOR_FIELDS = {
        'soil_moisture', 'temperature', 'light_intensity',
        'humidity', 'co2_level', 'prev_temperature',
    }

    def set_sensors(self, **kwargs):
        with self._lock:
            for key, val in kwargs.items():
                if key in self._SENSOR_FIELDS:
                    setattr(self, key, val)

    # ---------- Bom ----------

    def is_pump_on(self):
        with self._lock:
            return self.pump_on

    def set_pump(self, on, trigger="AUTO"):
        """Bat/tat bom. Tra ve True neu trang thai thay doi (de trigger event publish)."""
        with self._lock:
            old = self.pump_on
            self.pump_on = on
            changed = old != on
            if changed:
                self.total_pump_cycles += 1
                record = BanGhiTuoi(
                    "ON" if on else "OFF",
                    self.soil_moisture,
                    self._get_sim_time_str_internal(),
                    trigger,
                )
                self._watering_log.append(record)
                if len(self._watering_log) > 200:
                    self._watering_log = self._watering_log[-100:]
            return changed

    def get_pump_duty(self):
        with self._lock:
            return self.pump_duty_cycle

    def set_pump_duty(self, duty):
        with self._lock:
            self.pump_duty_cycle = max(0.0, min(100.0, duty))

    # FIX: Them method public de PumpTask cap nhat thong ke bom
    def add_pump_runtime(self, seconds, water_liters=0.05):
        """Cap nhat thoi gian chay bom va luong nuoc tieu thu (thread-safe)."""
        with self._lock:
            self.pump_run_time    += seconds
            self.total_water_used += water_liters

    # ---------- Che do ----------

    def get_mode(self):
        with self._lock:
            return self.mode

    def set_mode(self, mode):
        with self._lock:
            if mode in ("AUTO", "MANUAL"):
                self.mode = mode

    def get_threshold(self):
        with self._lock:
            return self.moisture_threshold

    def set_threshold(self, value):
        with self._lock:
            self.moisture_threshold = max(10.0, min(80.0, value))

    # ---------- PID ----------

    def get_pid_state(self):
        with self._lock:
            return self.pid_state.to_dict()

    def set_pid_state(self, error, integral, derivative, output):
        with self._lock:
            self.pid_state.error      = error
            self.pid_state.integral   = integral
            self.pid_state.derivative = derivative
            self.pid_state.output     = output

    def get_pid_setpoint(self):
        with self._lock:
            return self.pid_state.setpoint

    def set_pid_setpoint(self, sp):
        with self._lock:
            self.pid_state.setpoint = max(10.0, min(80.0, sp))

    # ---------- Thoi tiet ----------

    def get_weather(self):
        with self._lock:
            return self.weather.to_dict()

    def get_weather_event_end_minutes(self):
        """Tra ve thoi diem ket thuc su kien theo sim_minutes tuyet doi."""
        with self._lock:
            return self.weather.event_end_minutes

    def set_weather(self, condition, cloud_cover, rain_intensity, end_minutes):
        """
        FIX: end_minutes la sim_minutes tuyet doi (khong phai sim_hour trong ngay)
        Tranh bug su kien khong ket thuc khi qua 24h.
        """
        with self._lock:
            self.weather.condition        = condition
            self.weather.cloud_cover      = cloud_cover
            self.weather.rain_intensity   = rain_intensity
            self.weather.event_end_minutes = end_minutes

    # ---------- AI ----------

    def get_ai_status(self):
        with self._lock:
            return {
                "status":         self.ai_status,
                "confidence":     round(self.ai_confidence, 2),
                "recommendation": self.ai_recommendation,
            }

    def set_ai_status(self, status, confidence, recommendation=""):
        with self._lock:
            self.ai_status         = status
            self.ai_confidence     = confidence
            self.ai_recommendation = recommendation

    # ---------- Canh bao ----------

    def add_alert(self, alert_type, message, severity="WARNING"):
        with self._lock:
            sim_str = self._get_sim_time_str_internal()
            record  = BanGhiCanhBao(alert_type, message, severity, sim_str)
            self._alert_history.append(record)
            self.alerts_fired += 1
            mx = self._config.ALERT_MAX_HISTORY
            if len(self._alert_history) > mx:
                self._alert_history = self._alert_history[-mx:]

    def get_recent_alerts(self, count=10):
        with self._lock:
            return [a.to_dict() for a in self._alert_history[-count:]]

    # ---------- Lich su tuoi ----------

    def get_watering_log(self, count=20):
        with self._lock:
            return [l.to_dict() for l in self._watering_log[-count:]]

    def get_latest_watering_event(self):
        """Lay ban ghi tuoi moi nhat (dung de publish event MQTT)."""
        with self._lock:
            if self._watering_log:
                return self._watering_log[-1].to_dict()
            return None

    # ---------- Snapshot ----------

    def get_snapshot(self):
        with self._lock:
            return {
                "sim_time":       self._get_sim_time_str_internal(),
                "sim_day":        int(self._sim_minutes // (24 * 60)) + 1,
                "real_time":      datetime.now().strftime("%H:%M:%S"),
                "soil_moisture":  round(self.soil_moisture, 1),
                "temperature":    round(self.temperature, 1),
                "light_intensity": round(self.light_intensity, 0),
                "humidity":       round(self.humidity, 1),
                "co2_level":      round(self.co2_level, 0),
                "pump_on":        self.pump_on,
                "pump_duty":      round(self.pump_duty_cycle, 1),
                "mode":           self.mode,
                "threshold":      self.moisture_threshold,
                "weather":        self.weather.condition,
                "ai_status":      self.ai_status,
            }

    # ---------- Thong ke ----------

    def get_statistics(self):
        with self._lock:
            return {
                "total_pump_cycles": self.total_pump_cycles,
                "total_water_used":  round(self.total_water_used, 1),
                "pump_run_time":     round(self.pump_run_time, 0),
                "alerts_fired":      self.alerts_fired,
                "watering_logs":     len(self._watering_log),
                "current_mode":      self.mode,
                "sim_day":           int(self._sim_minutes // (24 * 60)) + 1,
            }

    # ---------- Noi bo ----------

    def _get_sim_time_str_internal(self):
        total = self._sim_minutes % (24 * 60)
        return f"{int(total // 60):02d}:{int(total % 60):02d}"
