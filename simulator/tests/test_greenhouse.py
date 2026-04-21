"""
Unit tests cho Greenhouse model.
"""
import pytest
from unittest.mock import Mock
from models.greenhouse import Greenhouse, BanGhiTuoi, BanGhiCanhBao


class MockConfig:
    """Mock config cho testing."""
    DAY_START_HOUR = 6
    DAY_END_HOUR = 18
    TIME_SCALE = 1
    MOISTURE_INIT = 50.0
    MOISTURE_LOW = 40.0
    MOISTURE_TARGET = 50.0
    ALERT_MAX_HISTORY = 200


@pytest.fixture
def mock_config():
    return MockConfig()


@pytest.fixture
def greenhouse(mock_config):
    return Greenhouse(mock_config)


def test_greenhouse_init(greenhouse, mock_config):
    """Test khoi tao Greenhouse."""
    assert greenhouse.soil_moisture == mock_config.MOISTURE_INIT
    assert greenhouse.temperature == 25.0
    assert greenhouse.mode == "AUTO"
    assert greenhouse.moisture_threshold == mock_config.MOISTURE_LOW
    assert greenhouse.pid_state.setpoint == mock_config.MOISTURE_TARGET


def test_update_sim_time(greenhouse):
    """Test cap nhat thoi gian mo phong."""
    initial_minutes = greenhouse._sim_minutes
    greenhouse.update_sim_time()
    # Thoi gian se tang sau khi update
    assert greenhouse._sim_minutes >= initial_minutes


def test_get_sim_hour_float(greenhouse):
    """Test lay gio mo phong."""
    hour = greenhouse.get_sim_hour_float()
    assert 0 <= hour < 24


def test_is_daytime(greenhouse):
    """Test kiem tra ban ngay."""
    # Voi DAY_START_HOUR = 6, luc 6h se la ban ngay
    greenhouse._sim_minutes = 6 * 60  # 6:00
    assert greenhouse.is_daytime() == True
    greenhouse._sim_minutes = 18 * 60  # 18:00
    assert greenhouse.is_daytime() == False


def test_get_sensors(greenhouse):
    """Test lay du lieu cam bien."""
    sensors = greenhouse.get_sensors()
    assert 'soil_moisture' in sensors
    assert 'temperature' in sensors
    assert 'light_intensity' in sensors
    assert 'humidity' in sensors
    assert 'co2_level' in sensors


def test_set_mode(greenhouse):
    """Test thay doi che do."""
    greenhouse.set_mode("MANUAL")
    assert greenhouse.get_mode() == "MANUAL"


def test_pump_control(greenhouse):
    """Test dieu khien bom."""
    greenhouse.set_pump(True, "test")
    assert greenhouse.is_pump_on() == True
    greenhouse.set_pump(False, "test")
    assert greenhouse.is_pump_on() == False


def test_watering_log_from_pump(greenhouse):
    """Test ban ghi tuoi tu set_pump."""
    greenhouse.set_pump(True, "test")
    log = greenhouse.get_watering_log()
    assert len(log) >= 1
    assert log[-1]['action'] == "ON"


def test_add_alert(greenhouse):
    """Test them canh bao."""
    greenhouse.add_alert("WARNING", "Do am thap", "medium")
    alerts = greenhouse.get_recent_alerts()
    assert len(alerts) == 1
    assert alerts[0]['type'] == "WARNING"
    assert alerts[0]['message'] == "Do am thap"


def test_pid_state(greenhouse):
    """Test trang thai PID."""
    pid = greenhouse.get_pid_state()
    assert 'output' in pid
    assert 'setpoint' in pid
    assert pid['setpoint'] == 50.0


def test_weather_state(greenhouse):
    """Test trang thai thoi tiet."""
    weather = greenhouse.get_weather()
    assert 'condition' in weather
    assert weather['condition'] == "clear"