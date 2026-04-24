"""
Nha Kinh Thong Minh - Mo hinh du lieu nha kinh
================================================
Thread-safe shared state cho tat ca cac task.

CHANGES:
  - Them add_pump_runtime() de PumpTask khoi vi pham encapsulation
  - _lock giu la private, khong truy cap tu ben ngoai
"""

import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from models.crop_model import CropModel, CropState
import logging
import threading

logger = logging.getLogger("greenhouse")

# FIX: Đã chuyển sang threading.Lock thay vì DummyLock
# Vì Paho MQTT dùng loop_start() (background thread) để tránh chặn IO khi đứt mạng,
# _on_message() sẽ được gọi từ thread phụ. Do đó phải dùng Lock thật để đảm bảo Thread-safe.


class BanGhiTuoi:
    """Mot ban ghi tuoi nuoc."""
    def __init__(self, action: str, moisture: float, sim_time_str: str, trigger: str) -> None:
        self.action: str = action
        self.moisture: float = moisture
        self.sim_time: str = sim_time_str
        self.real_time: str = datetime.now().strftime("%H:%M:%S")
        self.trigger: str = trigger

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action":    self.action,
            "moisture":  round(self.moisture, 1),
            "sim_time":  self.sim_time,
            "real_time": self.real_time,
            "trigger":   self.trigger,
        }


class BanGhiCanhBao:
    """Mot ban ghi canh bao."""
    def __init__(self, alert_type: str, message: str, severity: str, sim_time_str: str) -> None:
        self.alert_type: str = alert_type
        self.message: str = message
        self.severity: str = severity
        self.sim_time: str = sim_time_str
        self.real_time: str = datetime.now().strftime("%H:%M:%S")
        self.acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
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
    def __init__(self) -> None:
        self.error: float = 0.0
        self.integral: float = 0.0
        self.derivative: float = 0.0
        self.output: float = 0.0
        self.setpoint: float = 50.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "error":      round(self.error, 2),
            "integral":   round(self.integral, 2),
            "derivative": round(self.derivative, 2),
            "output":     round(self.output, 1),
            "setpoint":   round(self.setpoint, 1),
        }


class TrangThaiThoiTiet:
    """Trang thai thoi tiet."""
    def __init__(self) -> None:
        self.condition: str = "clear"
        self.cloud_cover: float = 0.0
        self.rain_intensity: float = 0.0
        # FIX: luu absolute sim_minutes thay vi sim_hour-trong-ngay
        self.event_end_minutes: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
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
        # FIX: Dung threading.Lock thay vi DummyLock de bao ve state khoi background thread
        self._lock            = threading.Lock()
        self._config          = config
        self._last_real_time  = time.time()
        self._sim_minutes     = config.DAY_START_HOUR * 60

        # Cam bien chinh
        self.soil_moisture  = config.MOISTURE_INIT
        self.temperature    = 25.0
        self.light_intensity = 0.0

        # Cam bien mo rong
        self.humidity          = 65.0
        self.co2_level         = 450.0
        self.prev_temperature  = 25.0

        # Cam bien dinh duong / hoa hoc (v6.0)
        self.ec_level = getattr(config, 'EC_INIT', 2.0)   # mS/cm
        self.ph_level = getattr(config, 'PH_INIT', 6.5)   # pH

        # Mo hinh cay trong (v7.0 - FAO-56 Kc + WSI)
        self.crop_model = CropModel(config)
        self.crop_state = self.crop_model.state

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
        self.ai_camera_result  = None

        # Lich su
        self._watering_log   = []
        self._alert_history  = []

        # Thong ke
        self.total_pump_cycles = 0
        self.alerts_fired      = 0
        self.watering_events_count = 0
        


    # ---------- Thoi gian mo phong ----------

    def update_sim_time(self) -> None:
        with self._lock:
            now   = time.time()
            delta = now - self._last_real_time
            self._last_real_time = now
            
            # FIX: Chống OS Sleep / Hibernate leap
            # Nếu thời gian thực trôi qua quá lớn (>10 giây giữa 2 tick), có khả năng hệ điều hành đã Sleep.
            # Ta kìm hãm delta để không làm thời gian mô phỏng nhảy vọt gây sai lệch vĩnh viễn hệ sinh thái.
            if delta > 10.0:
                logger.warning(f"  [GREENHOUSE] Phát hiện OS Sleep/Block (delta={delta:.1f}s). Clamping thời gian để bảo vệ mô phỏng.")
                delta = 10.0
                
            self._sim_minutes += (delta / 60.0) * self._config.TIME_SCALE

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

    def get_sensors(self) -> Dict[str, float]:
        with self._lock:
            return {
                "soil_moisture":   round(self.soil_moisture, 1),
                "temperature":     round(self.temperature, 1),
                "light_intensity": round(self.light_intensity, 0),
                "humidity":        round(self.humidity, 1),
                "co2_level":       round(self.co2_level, 0),
                "ec_level":        round(self.ec_level, 2),
                "ph_level":        round(self.ph_level, 2),
            }

    # ---------- Crop Model ----------

    def get_crop_state(self) -> Dict[str, Any]:
        """Tra ve trang thai mo hinh cay trong (Kc, WSI, giai doan)."""
        with self._lock:
            return self.crop_state.to_dict()

    def update_crop_model(self, sim_day: int, soil_moisture: float,
                          light_norm: float, temperature: float,
                          is_day: bool, dt_factor: float) -> CropState:
        """Cap nhat mo hinh cay trong va tra ve trang thai moi."""
        with self._lock:
            self.crop_state = self.crop_model.update(
                sim_day, soil_moisture, light_norm,
                temperature, is_day, dt_factor
            )
            return self.crop_state

    # Whitelist cac truong cam bien duoc phep cap nhat qua set_sensors()
    _SENSOR_FIELDS = {
        'soil_moisture', 'temperature', 'light_intensity',
        'humidity', 'co2_level', 'prev_temperature',
        'ec_level', 'ph_level',
    }

    def set_sensors(self, **kwargs: Any) -> None:
        with self._lock:
            for key, val in kwargs.items():
                if key in self._SENSOR_FIELDS:
                    setattr(self, key, val)

    # ---------- Bom ----------

    def is_pump_on(self) -> bool:
        with self._lock:
            return self.pump_on

    def set_pump(self, on: bool, trigger: str = "AUTO") -> bool:
        """Bat/tat bom. Tra ve True neu trang thai thay doi (de trigger event publish)."""
        with self._lock:
            old = self.pump_on
            self.pump_on = on
            changed = old != on
            if changed:
                if on:
                    self.total_pump_cycles += 1
                record = BanGhiTuoi(
                    "ON" if on else "OFF",
                    self.soil_moisture,
                    self._get_sim_time_str_internal(),
                    trigger,
                )
                self._watering_log.append(record)
                self.watering_events_count += 1
                if len(self._watering_log) > 200:
                    self._watering_log = self._watering_log[-100:]
            return changed

    def get_pump_duty(self) -> float:
        with self._lock:
            return self.pump_duty_cycle

    def set_pump_duty(self, duty: float) -> None:
        with self._lock:
            self.pump_duty_cycle = max(0.0, min(100.0, duty))

    # FIX: Them method public de PumpTask cap nhat thong ke bom
    def add_pump_runtime(self, seconds: float, water_liters: float = 0.05) -> None:
        """Cap nhat thoi gian chay bom va luong nuoc tieu thu (thread-safe)."""
        with self._lock:
            self.pump_run_time    += seconds
            self.total_water_used += water_liters

    # ---------- Che do ----------

    def get_mode(self) -> str:
        with self._lock:
            return self.mode

    def set_mode(self, mode: str) -> None:
        with self._lock:
            if mode in ("AUTO", "MANUAL"):
                if mode == "AUTO" and self.mode != "AUTO":
                    # FIX: Reset PID integral khi chuyen tu MANUAL sang AUTO tranh windup
                    self.pid_state.integral = 0.0
                self.mode = mode

    def get_threshold(self) -> float:
        with self._lock:
            return self.moisture_threshold

    def set_threshold(self, value: float) -> None:
        with self._lock:
            self.moisture_threshold = max(10.0, min(80.0, value))

    # ---------- PID ----------

    def get_pid_state(self) -> Dict[str, float]:
        with self._lock:
            return self.pid_state.to_dict()

    def set_pid_state(self, error: float, integral: float, derivative: float, output: float) -> None:
        with self._lock:
            self.pid_state.error      = error
            self.pid_state.integral   = integral
            self.pid_state.derivative = derivative
            self.pid_state.output     = output

    def get_pid_setpoint(self) -> float:
        with self._lock:
            return self.pid_state.setpoint

    def set_pid_setpoint(self, sp: float) -> None:
        with self._lock:
            self.pid_state.setpoint = max(10.0, min(80.0, sp))

    # ---------- Thoi tiet ----------

    def get_weather(self) -> Dict[str, Any]:
        with self._lock:
            return self.weather.to_dict()

    def get_weather_event_end_minutes(self) -> float:
        """Tra ve thoi diem ket thuc su kien theo sim_minutes tuyet doi."""
        with self._lock:
            return self.weather.event_end_minutes

    def set_weather(self, condition: str, cloud_cover: float, rain_intensity: float, end_minutes: float) -> None:
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

    def get_ai_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status":         self.ai_status,
                "confidence":     round(self.ai_confidence, 2),
                "recommendation": self.ai_recommendation,
            }

    def set_ai_status(self, status: str, confidence: float, recommendation: str = "") -> None:
        with self._lock:
            self.ai_status         = status
            self.ai_confidence     = confidence
            self.ai_recommendation = recommendation

    def get_ai_camera_result(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.ai_camera_result

    def set_ai_camera_result(self, result: Dict[str, Any]) -> None:
        with self._lock:
            self.ai_camera_result = result

    # ---------- Canh bao ----------

    def add_alert(self, alert_type: str, message: str, severity: str = "WARNING") -> None:
        with self._lock:
            sim_str = self._get_sim_time_str_internal()
            record  = BanGhiCanhBao(alert_type, message, severity, sim_str)
            self._alert_history.append(record)
            self.alerts_fired += 1
            mx = self._config.ALERT_MAX_HISTORY
            if len(self._alert_history) > mx:
                self._alert_history = self._alert_history[-mx:]

    def get_recent_alerts(self, count: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._alert_history[-count:]]

    # ---------- Lich su tuoi ----------

    def get_watering_log(self, count: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return [l.to_dict() for l in self._watering_log[-count:]]

    def get_latest_watering_event(self) -> Optional[Dict[str, Any]]:
        """Lay ban ghi tuoi moi nhat (dung de publish event MQTT)."""
        with self._lock:
            if self._watering_log:
                return self._watering_log[-1].to_dict()
            return None

    # ---------- Snapshot ----------

    def get_snapshot(self) -> Dict[str, Any]:
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
                "ec_level":       round(self.ec_level, 2),
                "ph_level":       round(self.ph_level, 2),
                "pump_on":        self.pump_on,
                "pump_duty":      round(self.pump_duty_cycle, 1),
                "mode":           self.mode,
                "threshold":      self.moisture_threshold,
                "weather":        self.weather.condition,
                "ai_status":      self.ai_status,
                "crop":           self.crop_state.to_dict(),
            }

    def get_internal_state(self) -> Dict[str, Any]:
        """ FIX Bug An 8: Tra ve toan bo state ma khong vi pham encapsulation """
        with self._lock:
            return {
                "sim_minutes": self._sim_minutes,
                "soil_moisture": self.soil_moisture,
                "temperature": self.temperature,
                "light_intensity": self.light_intensity,
                "humidity": self.humidity,
                "co2_level": self.co2_level,
                "ec_level": self.ec_level,
                "ph_level": self.ph_level,
                "pump_on": self.pump_on,
                "pump_duty_cycle": self.pump_duty_cycle,
                "total_water_used": self.total_water_used,
                "pump_run_time": self.pump_run_time,
                "mode": self.mode,
                "moisture_threshold": self.moisture_threshold,
                "total_pump_cycles": self.total_pump_cycles,
                "alerts_fired": self.alerts_fired,
                "pid_setpoint": self.pid_state.setpoint,
                "watering_events_count": self.watering_events_count,
                "crop_day": self.crop_state.crop_day,
            }

    def restore_internal_state(self, data: Dict[str, Any]) -> None:
        """ FIX Bug An 8: Restore state an toan (thread-safe) """
        with self._lock:
            self._sim_minutes = data.get("sim_minutes", self._sim_minutes)
            self.soil_moisture = max(0.0, min(100.0, data.get("soil_moisture", self.soil_moisture)))
            self.temperature = max(-50.0, min(100.0, data.get("temperature", self.temperature)))
            self.light_intensity = max(0.0, min(100000.0, data.get("light_intensity", self.light_intensity)))
            self.humidity = max(0.0, min(100.0, data.get("humidity", self.humidity)))
            self.co2_level = max(0.0, min(5000.0, data.get("co2_level", self.co2_level)))
            self.ec_level = max(0.0, min(10.0, data.get("ec_level", self.ec_level)))
            self.ph_level = max(0.0, min(14.0, data.get("ph_level", self.ph_level)))
            self.pump_on = bool(data.get("pump_on", False))
            self.pump_duty_cycle = max(0.0, min(100.0, data.get("pump_duty_cycle", 0.0)))
            self.total_water_used = max(0.0, data.get("total_water_used", self.total_water_used))
            self.pump_run_time = max(0.0, data.get("pump_run_time", self.pump_run_time))
            mode = data.get("mode", self.mode)
            self.mode = mode if mode in ("AUTO", "MANUAL") else "AUTO"
            self.moisture_threshold = max(10.0, min(80.0, data.get("moisture_threshold", self.moisture_threshold)))
            self.total_pump_cycles = max(0, int(data.get("total_pump_cycles", self.total_pump_cycles)))
            self.alerts_fired = max(0, int(data.get("alerts_fired", self.alerts_fired)))
            self.watering_events_count = max(0, int(data.get("watering_events_count", self.watering_events_count)))
            self.pid_state.setpoint = max(10.0, min(80.0, data.get("pid_setpoint", self.pid_state.setpoint)))
            # Crop model: khoi phuc ngay (giai doan tu tinh lai tu sim_day)
            restored_crop_day = data.get("crop_day", self.crop_state.crop_day)
            self.crop_state.crop_day = max(1, min(self.crop_state.total_days, restored_crop_day))

    # ---------- Thong ke ----------

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_pump_cycles": self.total_pump_cycles,
                "total_water_used":  round(self.total_water_used, 1),
                "pump_run_time":     round(self.pump_run_time, 0),
                "alerts_fired":      self.alerts_fired,
                "watering_logs":     len(self._watering_log),
                "watering_events_count": self.watering_events_count,
                "current_mode":      self.mode,
                "sim_day":           int(self._sim_minutes // (24 * 60)) + 1,
            }

    # ---------- Noi bo ----------

    def _get_sim_time_str_internal(self) -> str:
        total = self._sim_minutes % (24 * 60)
        return f"{int(total // 60):02d}:{int(total % 60):02d}"
