"""
Test PID Controller - NANG CAP v3.0
Kiem tra:
  [1] Deadband (Stability Margin) - chong chattering
  [2] Derivative Low-Pass Filter - chong nhieu spike
  [3] dt chinh xac: KHONG nhan TIME_SCALE
  [4] Feedforward Rain suppression
  [5] Anti-windup integral clamp
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import unittest
from unittest.mock import MagicMock, patch
from tasks.pump_task import PumpTask, _DERIV_FILTER_ALPHA


class DummyConfig:
    PID_ENABLED           = True
    PID_KP                = 2.0
    PID_KI                = 0.1
    PID_KD                = 0.5
    PID_INTEGRAL_MAX      = 50.0
    PID_OUTPUT_MIN        = 0.0
    PID_OUTPUT_MAX        = 100.0
    PID_DEADBAND          = 2.0
    TASK_INTERVAL_PUMP    = 1.0
    TIME_SCALE            = 10    # PID PHAI KHONG nhan so nay
    WEATHER_RAIN_PUMP_THRESHOLD = 0.4
    MAX_PUMP_DURATION_SEC = 300
    THRESHOLD_DEADBAND    = 2.0


class TestPIDController(unittest.TestCase):

    def _make_task(self, moisture=50.0, setpoint=50.0, integral=0.0, condition='clear', rain_intensity=0.0):
        config = DummyConfig()
        gh     = MagicMock()
        gh.get_weather.return_value = {"condition": condition, "rain_intensity": rain_intensity}
        gh.is_pump_on.return_value  = False
        gh.get_pid_setpoint.return_value = setpoint
        gh.get_sensors.return_value = {"soil_moisture": moisture, "temperature": 25.0}

        self.pid_state = {"integral": integral, "derivative": 0.0}
        self.last_output = None

        def set_pid_state(e, i, d, o):
            self.pid_state["integral"]   = i
            self.pid_state["derivative"] = d
            self.last_output             = o

        gh.get_pid_state.return_value = self.pid_state
        gh.set_pid_state   = set_pid_state
        gh.set_pump_duty   = MagicMock()
        gh.set_pump        = MagicMock()

        task = PumpTask(gh, config)
        task.last_time = time.time() - 1.0   # Gia lap da qua 1 giay thuc
        return task, gh, config

    # ------------------------------------------------------------------
    def test_deadband_zero_output(self):
        """Trong vung chet (|error| < 2%), output phai = 0 va integral = 0."""
        task, gh, _ = self._make_task(moisture=48.5, setpoint=50.0)
        # error = 1.5 < PID_DEADBAND = 2.0 -> deadband
        task._pid_control()
        self.assertEqual(self.last_output, 0.0,
                         "Output phai = 0 khi nam trong vung chet")
        self.assertEqual(self.pid_state["integral"], 0.0,
                         "Integral khong duoc tich luy trong vung chet (anti-windup)")

    def test_aggressive_correction_low_moisture(self):
        """Khi do am xuong thap, PID phai chay cong suat cao."""
        task, gh, _ = self._make_task(moisture=20.0, setpoint=50.0)
        task._pid_control()
        # KP * error = 2.0 * 30 = 60, nen output > 60
        self.assertGreater(self.last_output, 60.0,
                           "Output phai cao khi do am rat thap")
        gh.set_pump_duty.assert_called_once()

    def test_dt_does_not_use_time_scale(self):
        """
        Kiem tra dt KHONG nhan TIME_SCALE.

        Cong thuc PID su dung trong code:
          integral += error * dt          (tich luy raw error*dt)
          output = KP*error + KI*integral + KD*deriv  (KI nhan integral)

        Sau 1 tick voi dt_real=1.0s, error=20:
          integral = 0 + 20 * 1.0 = 20.0   (dung - khong nhan TIME_SCALE)

        NEU bi nhan TIME_SCALE=10:
          integral = 0 + 20 * 10.0 = 200.0  (sai - qua lon)

        Nen kiem tra integral < 50 (PID_INTEGRAL_MAX) va > 15
        de dam bao dt la ~1s thuc, khong phai 10s (TIME_SCALE=10).
        """
        task, gh, cfg = self._make_task(moisture=30.0, setpoint=50.0)
        # error = 20, dt_real ~ 1.0s
        # Correct: integral = 20 * 1.0 = 20.0
        # Wrong (TIME_SCALE bug): integral = 20 * 10.0 = 200 -> clamped to 50
        task._pid_control()
        i = self.pid_state["integral"]
        # Neu bi nhan TIME_SCALE=10: i >= 50 (clamp toi da)
        self.assertLess(i, cfg.PID_INTEGRAL_MAX,
                        f"Integral bi clamp ({i}) - co the dang nhan TIME_SCALE!")
        # Dam bao co gia tri thuc su (khong phai 0)
        self.assertGreater(abs(i), 1.0,
                           "Integral phai co gia tri sau 1 tick")
        # Dam bao dt ~ 1.0s (integral = error * dt = 20 * dt -> dt = i/20)
        inferred_dt = i / 20.0
        self.assertLess(inferred_dt, cfg.TASK_INTERVAL_PUMP * 3,
                        f"dt suy ra ({inferred_dt:.2f}s) qua lon - kha nang dang nhan TIME_SCALE")

    def test_derivative_lowpass_filter(self):
        """Derivative term phai duoc loc boi LPF (gia tri phai nho hon raw)."""
        task, gh, _ = self._make_task(moisture=30.0, setpoint=50.0)
        task.prev_error  = 50.0 - 60.0   # Gia lap error cu lon
        task._prev_deriv = 0.0
        task._pid_control()
        # Raw deriv = (error - prev_error) / dt = (20 - (-10)) / 1 = 30
        # LPF output = 0.3 * 30 + 0.7 * 0 = 9 (khong phai 30)
        filtered = self.pid_state["derivative"]
        self.assertLess(abs(filtered), 30.0,
                        "Derivative phai duoc loc (nho hon raw derivative)")

    def test_rain_suppression_turns_off_pump(self):
        """Khi dang mua du manh, bom phai tat va PID reset."""
        task, gh, _ = self._make_task(
            moisture=30.0, condition='rainy', rain_intensity=0.8
        )
        gh.is_pump_on.return_value = True
        task._pid_control()
        gh.set_pump.assert_called_once_with(False, trigger="RAIN_DETECTED")

    def test_integral_antiwindup(self):
        """Integral phai bi clamp o PID_INTEGRAL_MAX."""
        task, gh, _ = self._make_task(
            moisture=5.0, setpoint=50.0, integral=49.0
        )
        # error = 45, dt~1s, integral hien tai = 49
        # Sau 1 tick: integral = 49 + 45*1 = 94 -> phai bi clamp ve 50
        task._pid_control()
        self.assertLessEqual(self.pid_state["integral"], 50.0,
                             "Integral phai bi clamp o PID_INTEGRAL_MAX")

    def test_deriv_filter_alpha_constant(self):
        """Kiem tra hang so LPF duoc dinh nghia trong module."""
        self.assertGreater(_DERIV_FILTER_ALPHA, 0.0)
        self.assertLess(_DERIV_FILTER_ALPHA, 1.0)


if __name__ == '__main__':
    unittest.main()
