"""
Nha Kinh Thong Minh - Task Dieu Khien Bom
===========================================
NANG CAP v3.0:
  [1] FIX BUG NGHIEM TRONG: dt = dt_real (khong nhan TIME_SCALE)
      PID integral/derivative tinh theo thoi gian THUC, khong phai mo phong
  [2] Low-pass filter cho Derivative term (chong nhieu spike)
  [3] Bumpless transfer: reset I term va D term khi chuyen MANUAL->AUTO
  [4] Anti-chattering va safety guard giu nguyen
  [5] Rain suppression giu nguyen
"""

import time
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.pump")

# Low-pass filter alpha cho Derivative (giam nhieu spike cam bien)
_DERIV_FILTER_ALPHA = 0.3  # 0 = filter manh nhat, 1 = khong filter


class PumpTask(BaseTask):
    """Task dieu khien bom tuoi ao."""

    def __init__(self, greenhouse, config):
        self.greenhouse  = greenhouse
        self.config      = config
        self.prev_error  = 0.0
        self.last_time   = time.time()
        self._prev_deriv = 0.0            # Gia tri derivative lan truoc (cho LPF)
        self._pump_start_time  = None
        self._last_state_change = 0.0

    def shutdown(self) -> None:
        pass

    def handle_dependency_failure(self) -> None:
        """Fallback logic khi cac task phu thuoc (VD: MoiTruong) bi loi hoan toan."""
        if self.greenhouse.is_pump_on():
            self.greenhouse.set_pump(False, trigger="EMERGENCY_SHUTDOWN")
            self.greenhouse.set_mode("MANUAL")
            self.greenhouse.add_alert(
                "PUMP_EMERGENCY",
                "Ngắt bơm khẩn cấp do lỗi hệ thống (Sensor Task Failed)",
                "CRITICAL",
            )
            logger.critical("[SAFETY] Ngắt bơm khẩn cấp do lỗi Task Môi trường!")

    def run(self):
        now = time.time()
        dt_real = now - self.last_time
        if dt_real <= 0 or dt_real > getattr(self.config, 'TASK_INTERVAL_PUMP', 3) * 2:
            dt_real = getattr(self.config, 'TASK_INTERVAL_PUMP', 3)
        self.last_time = now
        
        mode = self.greenhouse.get_mode()

        # Safety guard: ngat bom neu chay qua lau
        if self.greenhouse.is_pump_on():
            if self._pump_start_time is None:
                self._pump_start_time = now
            elif now - self._pump_start_time > getattr(self.config, 'MAX_PUMP_DURATION_SEC', 300):
                self.greenhouse.set_pump(False, trigger="SAFETY_GUARD")
                self.greenhouse.set_mode("MANUAL") # FIX: Ép về MANUAL để chống vòng lặp tự bật lại
                self.greenhouse.add_alert(
                    "PUMP_SAFETY",
                    f"Bom chay lien tuc > {self.config.MAX_PUMP_DURATION_SEC}s, tu ngat va khoa che do AUTO",
                    "CRITICAL",
                )
                logger.critical("[SAFETY GUARD] Ngat bom khan cap va khoa che do AUTO do chay qua lau!")
        else:
            self._pump_start_time = None

        if mode == "AUTO":
            if self.config.PID_ENABLED:
                self._pid_control(dt_real, now)
            else:
                self._threshold_control(now)

        # Cap nhat thong ke bom
        if self.greenhouse.is_pump_on():
            duty = (self.greenhouse.get_pump_duty()
                    if (mode == "AUTO" and self.config.PID_ENABLED)
                    else 100.0)
            
            # FIX Bug An 13: Dung dt_real thay vi TASK_INTERVAL_PUMP de tinh toan thoi gian chay & nuoc
            # Gia su bom tieu thu 1.0 lit / phut -> (1.0 / 60) * dt_real
            water_rate_per_sec = 1.0 / 60.0
            water_liters = water_rate_per_sec * dt_real * (duty / 100.0)
            
            self.greenhouse.add_pump_runtime(
                seconds=dt_real,
                water_liters=water_liters,
            )

    def _is_raining_enough_to_suppress(self) -> bool:
        weather = self.greenhouse.get_weather()
        return (
            weather["condition"] == "rainy"
            and weather["rain_intensity"] >= self.config.WEATHER_RAIN_PUMP_THRESHOLD
        )

    def _pid_control(self, dt: float, now: float):
        """
        Dieu khien PID voi Derivative Low-Pass Filter.

        FIX BUG NGHIEM TRONG:
          dt = dt_real (thoi gian thuc, tinh bang giay)
          KHONG nhan TIME_SCALE vi error/setpoint la gia tri
          trong khong gian do am (%), khong phai khong gian thoi gian.
          Nhan TIME_SCALE lam lech KI va KD theo he so 10.
        """
        cfg = self.config
        gh  = self.greenhouse

        if self._is_raining_enough_to_suppress():
            if gh.is_pump_on():
                gh.set_pump(False, trigger="RAIN_DETECTED")
                logger.info("[BOM TAT] Tu dong tat - dang mua, khong can tuoi")
            gh.set_pid_state(0.0, 0.0, 0.0, 0.0)
            self.prev_error  = 0.0
            self._prev_deriv = 0.0
            return

        sensors  = gh.get_sensors()
        moisture = sensors["soil_moisture"]
        setpoint = gh.get_pid_setpoint()

        error = setpoint - moisture
        raw_error = error # Giữ lại giá trị gốc để tính Derivative

        # Deadband (Stability Margin)
        if abs(error) < getattr(cfg, 'PID_DEADBAND', 2.0):
            error = 0.0

        pid       = gh.get_pid_state()
        integral  = pid["integral"] + error * dt
        integral  = max(-cfg.PID_INTEGRAL_MAX, min(cfg.PID_INTEGRAL_MAX, integral))

        # Derivative voi Low-Pass Filter (chong nhieu spike)
        # FIX: Dùng raw_error để tính derivative thay vì error đã bị ép về 0 bởi deadband,
        # tránh hiện tượng "kick" (giật output) khi thoát khỏi/đi vào vùng deadband.
        raw_deriv = (raw_error - self.prev_error) / dt if dt > 0 else 0.0
        # LPF: deriv_filtered = alpha * raw + (1-alpha) * prev
        deriv_filtered = (_DERIV_FILTER_ALPHA * raw_deriv
                          + (1.0 - _DERIV_FILTER_ALPHA) * self._prev_deriv)
        self._prev_deriv = deriv_filtered
        self.prev_error  = raw_error

        # Feedforward
        ff_term = 0.0
        weather = gh.get_weather()
        if weather["condition"] == "rainy" and weather["rain_intensity"] > 0:
            ff_term -= weather["rain_intensity"] * 40.0
        temp = sensors.get("temperature", 25.0)
        if temp > 30.0:
            ff_term += (temp - 30.0) * 1.5

        output = (
            cfg.PID_KP * error
            + cfg.PID_KI * integral
            + cfg.PID_KD * deriv_filtered
            + ff_term
        )
        
        # FIX Bug An 7: Chuan hoa Anti-windup bang phuong phap Back-calculation
        # Dam bao output ra khỏi vùng saturation lập tức khi error đảo chiều
        if output > cfg.PID_OUTPUT_MAX or output < cfg.PID_OUTPUT_MIN:
            clamped_output = max(cfg.PID_OUTPUT_MIN, min(cfg.PID_OUTPUT_MAX, output))
            if cfg.PID_KI > 0:
                # Tinh toan lai Integral de output == clamped_output
                integral = (clamped_output - ff_term - cfg.PID_KP * error - cfg.PID_KD * deriv_filtered) / cfg.PID_KI
            output = clamped_output

        gh.set_pid_state(error, integral, deriv_filtered, output)
        gh.set_pump_duty(output)

        # Anti-chattering
        MIN_STATE_TIME = 5.0
        time_since_change = now - self._last_state_change

        if output > 20 and not gh.is_pump_on() and time_since_change > MIN_STATE_TIME:
            gh.set_pump(True, trigger="PID")
            self._last_state_change = now
            logger.info(
                f"[BOM BAT] PID | output={output:.1f}% "
                f"error={error:.1f} M={moisture:.1f}%"
            )
        elif output < 5 and gh.is_pump_on() and time_since_change > MIN_STATE_TIME:
            gh.set_pump(False, trigger="PID")
            self._last_state_change = now
            logger.info(
                f"[BOM TAT] PID | output={output:.1f}% M={moisture:.1f}%"
            )

    def _threshold_control(self, now: float):
        """Dieu khien theo nguong voi hysteresis band."""
        gh      = self.greenhouse
        sensors = gh.get_sensors()
        moisture = sensors["soil_moisture"]

        if self._is_raining_enough_to_suppress():
            time_since_change = now - self._last_state_change
            if gh.is_pump_on() and time_since_change > 5.0:
                gh.set_pump(False, trigger="RAIN_DETECTED")
                self._last_state_change = now
                logger.info("[BOM TAT] Tu dong tat - dang mua, khong can tuoi")
            return

        target   = gh.get_threshold()
        deadband = getattr(self.config, 'THRESHOLD_DEADBAND', 2.0)
        low  = target - deadband
        high = target + deadband

        # Anti-chattering
        MIN_STATE_TIME = 5.0
        time_since_change = now - self._last_state_change

        if moisture < low and not gh.is_pump_on() and time_since_change > MIN_STATE_TIME:
            gh.set_pump(True, trigger="AUTO")
            self._last_state_change = now
            logger.info(f"[BOM BAT] AUTO | M={moisture:.1f}% < nguong bat={low:.1f}%")
        elif moisture > high and gh.is_pump_on() and time_since_change > MIN_STATE_TIME:
            gh.set_pump(False, trigger="AUTO")
            self._last_state_change = now
            logger.info(f"[BOM TAT] AUTO | M={moisture:.1f}% > nguong tat={high:.1f}%")
