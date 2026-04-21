"""
Nha Kinh Thong Minh - Task Dieu Khien Bom
===========================================
2 che do dieu khien:
- PID Controller: dieu khien chinh xac do am
- Threshold (Hysteresis): bat/tat don gian

FIX:
  - Khong con truy cap greenhouse._lock truc tiep
    (dung method add_pump_runtime() thay the)
  - Bom tu dong TAT khi dang mua (rain_intensity > nguong)
    va bat lai khi ngung mua
"""

import time
import logging

logger = logging.getLogger("task.pump")


class PumpTask:
    """Task dieu khien bom tuoi ao."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config     = config
        self.prev_error = 0.0
        self.last_time  = time.time()

    def run(self):
        mode = self.greenhouse.get_mode()

        if mode == "AUTO":
            if self.config.PID_ENABLED:
                self._pid_control()
            else:
                self._threshold_control()

        # FIX: Dung method public thay vi truy cap _lock truc tiep
        if self.greenhouse.is_pump_on():
            self.greenhouse.add_pump_runtime(
                seconds=self.config.TASK_INTERVAL_PUMP,
                water_liters=0.05,
            )

    def _is_raining_enough_to_suppress(self):
        """
        FIX: Kiem tra xem mua co du manh de tat bom khong.
        Tra ve True neu should suppress pump vi mua.
        """
        weather = self.greenhouse.get_weather()
        return (
            weather["condition"] == "rainy"
            and weather["rain_intensity"] >= self.config.WEATHER_RAIN_PUMP_THRESHOLD
        )

    def _pid_control(self):
        """Dieu khien PID."""
        cfg = self.config
        gh  = self.greenhouse

        # FIX: Tat bom va thoat som neu dang mua
        if self._is_raining_enough_to_suppress():
            if gh.is_pump_on():
                gh.set_pump(False, trigger="RAIN_DETECTED")
                logger.info("[BOM TAT] Tu dong tat - dang mua, khong can tuoi")
            return

        sensors  = gh.get_sensors()
        moisture = sensors["soil_moisture"]
        setpoint = gh.get_pid_setpoint()

        now = time.time()
        dt  = now - self.last_time
        if dt <= 0:
            dt = cfg.TASK_INTERVAL_PUMP
        self.last_time = now

        error = setpoint - moisture

        pid      = gh.get_pid_state()
        integral = pid["integral"] + error * dt
        integral = max(-cfg.PID_INTEGRAL_MAX, min(cfg.PID_INTEGRAL_MAX, integral))

        derivative    = (error - self.prev_error) / dt if dt > 0 else 0
        self.prev_error = error

        output = (
            cfg.PID_KP * error
            + cfg.PID_KI * integral
            + cfg.PID_KD * derivative
        )
        output = max(cfg.PID_OUTPUT_MIN, min(cfg.PID_OUTPUT_MAX, output))

        gh.set_pid_state(error, integral, derivative, output)
        gh.set_pump_duty(output)

        if output > 20 and not gh.is_pump_on():
            gh.set_pump(True, trigger="PID")
            logger.info(
                f"[BOM BAT] PID | output={output:.1f}% "
                f"error={error:.1f} M={moisture:.1f}%"
            )
        elif output < 5 and gh.is_pump_on():
            gh.set_pump(False, trigger="PID")
            logger.info(
                f"[BOM TAT] PID | output={output:.1f}% "
                f"M={moisture:.1f}%"
            )

    def _threshold_control(self):
        """Dieu khien theo nguong (hysteresis)."""
        gh      = self.greenhouse
        sensors = gh.get_sensors()
        moisture = sensors["soil_moisture"]

        # FIX: Tat bom neu dang mua
        if self._is_raining_enough_to_suppress():
            if gh.is_pump_on():
                gh.set_pump(False, trigger="RAIN_DETECTED")
                logger.info("[BOM TAT] Tu dong tat - dang mua, khong can tuoi")
            return

        low  = gh.get_threshold()
        high = self.config.MOISTURE_HIGH

        if moisture < low and not gh.is_pump_on():
            gh.set_pump(True, trigger="AUTO")
            logger.info(f"[BOM BAT] AUTO | M={moisture:.1f}% < nguong={low}%")
        elif moisture > high and gh.is_pump_on():
            gh.set_pump(False, trigger="AUTO")
            logger.info(f"[BOM TAT] AUTO | M={moisture:.1f}% > nguong={high}%")
