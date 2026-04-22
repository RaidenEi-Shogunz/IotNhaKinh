"""
Unit tests cho Greenhouse model - NANG CAP v3.0
Kiem tra them:
  - Magnus formula qua EnvironmentTask (_rh_from_dewpoint)
  - Transpiration effect (do am dat cao -> RH cao hon)
  - Gaussian spike model (spike_prob=0 cho ket qua on dinh)
"""
import sys
import os
import math
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.greenhouse import Greenhouse
from tasks.environment_task import EnvironmentTask, _rh_from_dewpoint


class MockConfig:
    DAY_START_HOUR = 6
    DAY_END_HOUR   = 18
    TIME_SCALE     = 1
    MOISTURE_INIT  = 50.0
    MOISTURE_LOW   = 40.0
    MOISTURE_TARGET= 50.0
    ALERT_MAX_HISTORY = 200
    TEMP_DAY_BASE    = 30.0
    TEMP_NIGHT_BASE  = 20.0
    TEMP_NOISE       = 0.3
    LIGHT_DAY_MAX    = 85000
    LIGHT_NIGHT_MAX  = 5
    LIGHT_NOISE      = 50
    HUMIDITY_BASE    = 65.0
    HUMIDITY_NOISE   = 1.0
    CO2_BASE         = 450.0
    CO2_NOISE        = 10.0
    CO2_MAX          = 1000.0
    MOISTURE_MIN_CLAMP    = 5.0
    MOISTURE_MAX_CLAMP    = 99.0
    MOISTURE_DECAY_DAY    = 0.15
    MOISTURE_DECAY_NIGHT  = 0.05
    MOISTURE_PUMP_RATE    = 3.0
    MOISTURE_RAIN_RATE    = 3.0
    THERMAL_INERTIA       = 0.7
    WEATHER_EVENT_CHANCE  = 0.0
    WEATHER_RAIN_DURATION = 2.0
    WEATHER_CLOUD_DURATION= 3.0
    WEATHER_RAIN_PUMP_THRESHOLD = 0.4
    PID_ENABLED           = False
    SOIL_TYPE             = 'loam'
    SOIL_PROPERTIES = {
        'loam': {'drainage_factor': 1.0, 'absorption_factor': 1.0, 'name': 'Dat pha'}
    }
    TASK_INTERVAL_ENVIRONMENT = 5
    SENSOR_SPIKE_PROB  = 0.0   # Tat spike trong test
    SENSOR_SPIKE_SIGMA = 2.0


class TestGreenhouse(unittest.TestCase):

    def setUp(self):
        self.config = MockConfig()
        self.gh     = Greenhouse(self.config)
        self.env    = EnvironmentTask(self.gh, self.config)

    # ------------------------------------------------------------------
    # Greenhouse model
    # ------------------------------------------------------------------
    def test_init(self):
        self.assertEqual(self.gh.soil_moisture, self.config.MOISTURE_INIT)
        self.assertEqual(self.gh.temperature, 25.0)
        self.assertEqual(self.gh.mode, "AUTO")
        self.assertEqual(self.gh.moisture_threshold, self.config.MOISTURE_LOW)
        self.assertEqual(self.gh.pid_state.setpoint, self.config.MOISTURE_TARGET)

    def test_update_sim_time(self):
        initial = self.gh._sim_minutes
        self.gh.update_sim_time()
        self.assertGreaterEqual(self.gh._sim_minutes, initial)

    def test_get_sim_hour_float(self):
        h = self.gh.get_sim_hour_float()
        self.assertGreaterEqual(h, 0)
        self.assertLess(h, 24)

    def test_is_daytime(self):
        self.gh._sim_minutes = 6 * 60
        self.assertTrue(self.gh.is_daytime())
        self.gh._sim_minutes = 18 * 60
        self.assertFalse(self.gh.is_daytime())

    def test_get_sensors_keys(self):
        sensors = self.gh.get_sensors()
        for key in ('soil_moisture', 'temperature', 'light_intensity', 'humidity', 'co2_level'):
            self.assertIn(key, sensors)

    def test_set_mode(self):
        self.gh.set_mode("MANUAL")
        self.assertEqual(self.gh.get_mode(), "MANUAL")

    def test_pump_on_off(self):
        self.gh.set_pump(True, "test")
        self.assertTrue(self.gh.is_pump_on())
        self.gh.set_pump(False, "test")
        self.assertFalse(self.gh.is_pump_on())

    def test_watering_log_populated(self):
        self.gh.set_pump(True, "test")
        log = self.gh.get_watering_log()
        self.assertGreaterEqual(len(log), 1)
        self.assertEqual(log[-1]['action'], "ON")

    def test_add_alert(self):
        self.gh.add_alert("WARNING", "Do am thap", "medium")
        alerts = self.gh.get_recent_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['type'], "WARNING")

    def test_pid_state_keys(self):
        pid = self.gh.get_pid_state()
        self.assertIn('output', pid)
        self.assertIn('setpoint', pid)
        self.assertEqual(pid['setpoint'], 50.0)

    def test_weather_init(self):
        weather = self.gh.get_weather()
        self.assertIn('condition', weather)
        self.assertEqual(weather['condition'], "clear")

    # ------------------------------------------------------------------
    # Magnus formula (_rh_from_dewpoint)
    # ------------------------------------------------------------------
    def test_magnus_saturation(self):
        """RH phai ~100% khi dew point = nhiet do."""
        rh = _rh_from_dewpoint(25.0, 25.0)
        self.assertAlmostEqual(rh, 100.0, delta=1.0,
                               msg=f"Expected ~100%, got {rh:.1f}%")

    def test_magnus_dry_air(self):
        """Dew point thap hon nhiet do rat nhieu -> RH thap."""
        rh = _rh_from_dewpoint(35.0, 5.0)
        self.assertLess(rh, 30.0,
                        msg=f"Expected < 30% khi dew point rat thap, got {rh:.1f}%")

    def test_magnus_clamping(self):
        """RH phai luon trong [20%, 100%]."""
        rh_high = _rh_from_dewpoint(20.0, 20.0)
        rh_low  = _rh_from_dewpoint(50.0, -10.0)
        self.assertLessEqual(rh_high, 100.0)
        self.assertGreaterEqual(rh_high, 20.0)
        self.assertGreaterEqual(rh_low, 20.0)
        self.assertLessEqual(rh_low, 100.0)

    def test_magnus_monotonic(self):
        """RH phai tang khi dew point tang (nhiet do co dinh)."""
        temp = 25.0
        rh1  = _rh_from_dewpoint(temp, 10.0)
        rh2  = _rh_from_dewpoint(temp, 15.0)
        rh3  = _rh_from_dewpoint(temp, 20.0)
        self.assertLess(rh1, rh2)
        self.assertLess(rh2, rh3)

    # ------------------------------------------------------------------
    # Transpiration effect on humidity
    # ------------------------------------------------------------------
    def test_transpiration_humidity_effect(self):
        """Do am dat cao hon -> RH cao hon (transpiration effect)."""
        self.gh._sim_minutes = 12 * 60
        weather = self.gh.get_weather()
        rh_low  = self.env._calc_humidity_magnus(True, weather, 25.0, soil_moisture=20.0)
        rh_high = self.env._calc_humidity_magnus(True, weather, 25.0, soil_moisture=80.0)
        self.assertGreater(rh_high, rh_low,
                           msg=f"Dat am (80%) phai cho RH cao hon dat kho (20%): {rh_low:.1f} vs {rh_high:.1f}")

    # ------------------------------------------------------------------
    # Transpiration reduces daytime moisture faster than nighttime
    # ------------------------------------------------------------------
    def test_transpiration_daytime_faster_decay(self):
        """Ban ngay co transpiration -> dat mat nuoc nhanh hon ban dem."""
        self.gh.set_sensors(soil_moisture=60.0)
        self.gh.set_pump(False)
        weather = self.gh.get_weather()

        m_noon  = self.env._calc_moisture(
            is_day=True, weather=weather, dt_factor=1.0,
            light=self.config.LIGHT_DAY_MAX, temperature=30.0
        )
        # Reset moisture
        self.gh.set_sensors(soil_moisture=60.0)
        m_night = self.env._calc_moisture(
            is_day=False, weather=weather, dt_factor=1.0,
            light=0, temperature=20.0
        )
        self.assertLess(m_noon, m_night,
                        msg="Ban ngay (co transpiration) phai lam mat nuoc nhanh hon ban dem")

    # ------------------------------------------------------------------
    # Spike model disabled -> stable output
    # ------------------------------------------------------------------
    def test_spike_disabled_stable(self):
        """Voi SENSOR_SPIKE_PROB=0, ket qua nhiet do on dinh (khong co outlier lon)."""
        self.assertEqual(self.env._spike_prob, 0.0)
        temps = []
        for _ in range(20):
            t = self.env._calc_temperature(
                sim_hour=12, is_day=True,
                weather={"condition": "clear", "cloud_cover": 0, "rain_intensity": 0},
                light=50000, dt_factor=1.0,
            )
            temps.append(t)
        spread = max(temps) - min(temps)
        self.assertLess(spread, 5.0,
                        msg=f"Voi spike_prob=0, spread phai < 5°C, got {spread:.1f}°C")


if __name__ == '__main__':
    unittest.main()
