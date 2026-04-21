"""
Integration tests cho toàn bộ hệ thống simulator.
"""
import time
import threading
import pytest
from unittest.mock import patch, MagicMock
from models.greenhouse import Greenhouse
from models.scheduler import CooperativeScheduler
from tasks.environment_task import EnvironmentTask
from tasks.pump_task import PumpTask
from tasks.alert_task import AlertTask


class MockConfig:
    """Mock config đầy đủ cho integration tests."""
    DAY_START_HOUR = 6
    DAY_END_HOUR = 18
    TIME_SCALE = 1
    MOISTURE_INIT = 50.0
    MOISTURE_LOW = 40.0
    MOISTURE_HIGH = 60.0
    MOISTURE_TARGET = 50.0
    MOISTURE_MIN_CLAMP = 5.0
    MOISTURE_MAX_CLAMP = 99.0
    ALERT_MAX_HISTORY = 200
    PID_ENABLED = True
    WEATHER_RAIN_PUMP_THRESHOLD = 5.0
    WEATHER_EVENT_CHANCE = 0.01
    WEATHER_RAIN_DURATION = 2.0
    WEATHER_CLOUD_DURATION = 3.0
    MOISTURE_DECAY_DAY = 0.15
    MOISTURE_DECAY_NIGHT = 0.05
    MOISTURE_PUMP_RATE = 3.0
    TEMP_DAY_BASE = 30.0
    TEMP_NIGHT_BASE = 20.0
    TEMP_NOISE = 0.3
    LIGHT_DAY_MAX = 10000
    LIGHT_NIGHT_MAX = 5
    HUMIDITY_BASE = 65.0
    CO2_BASE = 450.0
    PID_KP = 2.0
    PID_KI = 0.1
    PID_KD = 0.5
    THERMAL_INERTIA = 0.7
    LIGHT_NOISE = 50
    HUMIDITY_AMPLITUDE = 15.0
    HUMIDITY_NOISE = 1.0
    CO2_DAY_DROP = 80.0
    CO2_NIGHT_RISE = 60.0
    CO2_NOISE = 10.0
    PID_INTEGRAL_MAX = 50.0
    PID_OUTPUT_MIN = 0.0
    PID_OUTPUT_MAX = 100.0


@pytest.fixture
def mock_config():
    return MockConfig()


@pytest.fixture
def greenhouse(mock_config):
    return Greenhouse(mock_config)


@pytest.fixture
def scheduler():
    return CooperativeScheduler(watchdog_timeout=5)


def test_full_system_integration(greenhouse, scheduler, mock_config):
    """Test tích hợp toàn bộ hệ thống với các tasks."""
    # Khởi tạo tasks
    env_task = EnvironmentTask(greenhouse, mock_config)
    pump_task = PumpTask(greenhouse, mock_config)
    alert_task = AlertTask(greenhouse, mock_config)

    # Đăng ký tasks
    scheduler.register_task("Environment", env_task.run, interval=1, priority=5)
    scheduler.register_task("Pump", pump_task.run, interval=2, priority=7)
    scheduler.register_task("Alert", alert_task.run, interval=3, priority=3)

    # Chạy scheduler trong thread riêng với timeout ngắn
    import threading
    import time

    def run_scheduler():
        scheduler.run(tick_interval=0.1)  # Chạy với tick nhanh

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Chờ một chút để scheduler chạy
    time.sleep(2)

    # Dừng scheduler
    scheduler.stop()
    scheduler_thread.join(timeout=1)

    # Kiểm tra hệ thống đã chạy
    assert len(scheduler._tasks) == 3

    # Kiểm tra greenhouse state đã thay đổi
    sensors = greenhouse.get_sensors()
    assert 'temperature' in sensors
    assert 'soil_moisture' in sensors

    # Kiểm tra có diagnostics
    diagnostics = scheduler.get_diagnostics()
    assert len(diagnostics) > 0

    # Kiểm tra thời gian mô phỏng đã tiến
    assert greenhouse.get_sim_minutes_absolute() > 0


def test_task_interaction(greenhouse, mock_config):
    """Test tương tác giữa các tasks."""
    # Khởi tạo tasks
    env_task = EnvironmentTask(greenhouse, mock_config)
    pump_task = PumpTask(greenhouse, mock_config)

    # Chạy environment task để cập nhật sensors
    env_task.run()

    # Lấy moisture ban đầu
    initial_moisture = greenhouse.get_sensors()['soil_moisture']

    # Chạy pump task
    pump_task.run()

    # Kiểm tra pump có thể được bật nếu moisture thấp
    # (logic tùy thuộc vào implementation, chỉ test không crash)
    assert greenhouse.get_mode() in ["AUTO", "MANUAL"]


def test_persistence_integration(greenhouse, mock_config, tmp_path):
    """Test tích hợp persistence với SQLite."""
    from tasks.persistence_task import PersistenceTask

    # Tạo database tạm
    db_path = tmp_path / "test.db"
    mock_config.DB_PATH = str(db_path)

    persistence_task = PersistenceTask(greenhouse, mock_config)

    # Thêm dữ liệu test
    greenhouse.add_alert("WARNING", "Test alert", "medium")
    greenhouse.set_pump(True, "test")

    # Chạy persistence
    persistence_task.run()

    # Kiểm tra file database được tạo
    assert db_path.exists()

    # Kiểm tra có thể đọc lại (mock check)
    # Trong thực tế, có thể query database


def test_ai_integration(greenhouse, mock_config):
    """Test tích hợp AI analysis."""
    from tasks.ai_task import AITask

    ai_task = AITask(greenhouse, mock_config)

    # Chạy AI analysis
    ai_task.run()

    # Kiểm tra AI status được cập nhật
    assert greenhouse.ai_status != ""
    assert greenhouse.ai_confidence >= 0.0