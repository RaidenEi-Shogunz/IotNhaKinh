"""
Nha Kinh Thong Minh - Main Entry Point
========================================
Khoi tao tat ca thanh phan va chay Cooperative Scheduler.

Kien truc:
  Greenhouse (shared state)
       |
  Cooperative Scheduler (watchdog, health monitoring)
       |
  +----+----+----+----+----+----+
  |    |    |    |    |    |    |
  ENV  MQTT PUMP  AI  ALERT DB

Cach chay:
  pip install -r requirements.txt
  cp .env.example .env   (dien key Adafruit IO cua ban)
  python main.py
  Ctrl+C de dung

FIX: Dung RotatingFileHandler thay vi FileHandler thuong
     Tranh file log tang kich thuoc vo han (max 5MB x 3 files)
"""

import sys
import logging
from logging.handlers import RotatingFileHandler
import config
from models.greenhouse import Greenhouse
from models.state_manager import GreenhouseStateManager
from models.scheduler import CooperativeScheduler
from tasks.environment_task import EnvironmentTask
from tasks.pump_task import PumpTask
from tasks.mqtt_task import MQTTTask
from tasks.ai_task import AITask
from tasks.alert_task import AlertTask
from tasks.persistence_task import PersistenceTask
from tasks.api_task import APIServerTask
from tasks.predict_task import PredictiveTask


BANNER = r"""
 ____                      _      ____                     _
/ ___| _ __ ___   __ _ _ _| |_   / ___|_ __ ___  ___ _ __ | |__   ___  _   _ ___  ___
\___ \| '_ ` _ \ / _` | '__| __| | |  _| '__/ _ \/ _ \ '_ \| '_ \ / _ \| | | / __|/ _ \
 ___) | | | | | | (_| | |  | |_  | |_| | | |  __/  __/ | | | | | | (_) | |_| \__ \  __/
|____/|_| |_| |_|\__,_|_|   \__|  \____|_|  \___|\___|_| |_|_| |_|\___/ \__,_|___/\___|
"""


def setup_logging():
    """
    Cau hinh logging.
    FIX: Dung RotatingFileHandler (max 5MB/file, giu 3 file cu)
         Tranh log file tang khong gioi han theo thoi gian.
    """
    formatter = logging.Formatter(
        "%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
            
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)

    # FIX: RotatingFileHandler thay vi FileHandler
    file_handler = RotatingFileHandler(
        "greenhouse.log",
        maxBytes=5 * 1024 * 1024,   # 5 MB moi file
        backupCount=3,               # Giu toi da 3 file cu (greenhouse.log.1, .2, .3)
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)


def main():
    if config._validation_errors:
        print("Lỗi cấu hình hệ thống:")
        for err in config._validation_errors:
            print(f" - {err}")
        sys.exit(1)
        
    setup_logging()
    logger = logging.getLogger("main")

    for line in BANNER.strip().split("\n"):
        logger.info(line)
    logger.info("")
    logger.info("  IoT Smart Agriculture Simulation System v4.0")
    logger.info("=" * 60)

    logger.info(f"  MQTT Broker:    {config.MQTT_HOST}:{config.MQTT_PORT}")
    logger.info(f"  Username:       {config.ADAFRUIT_USERNAME}")
    logger.info(f"  Feeds:          {config.RATE_LIMIT_FEEDS_PER_PUBLISH} feeds")
    logger.info(f"  Rate Limit:     {config.RATE_LIMIT_POINTS_PER_MIN} pts/min")
    logger.info(f"  Publish Every:  {config.TASK_INTERVAL_MQTT}s")
    logger.info(f"  PID Enabled:    {config.PID_ENABLED}")
    logger.info(f"  Time Scale:     1 phut thuc = {config.TIME_SCALE} phut mo phong")
    logger.info(f"  Nguong do am:   {config.MOISTURE_LOW}% - {config.MOISTURE_HIGH}%")
    logger.info(f"  Rain suppress:  intensity >= {config.WEATHER_RAIN_PUMP_THRESHOLD}")
    logger.info(f"  API Port:       {config.API_PORT} (REST + WebSocket)")
    logger.info("=" * 60)
    logger.info("")

    # 1. Greenhouse model
    greenhouse = Greenhouse(config)

    # 1b. State Manager (Persistence - tach rieng theo SRP)
    state_manager = GreenhouseStateManager(greenhouse)
    if state_manager.load():
        logger.info("[OK] Da phuc hoi trang thai tu Snapshot (Persistence)")
    else:
        logger.info("[OK] Khoi tao trang thai Greenhouse moi")

    # 2. Tasks
    env_task         = EnvironmentTask(greenhouse, config)
    pump_task        = PumpTask(greenhouse, config)
    mqtt_task        = MQTTTask(greenhouse, config)
    ai_task          = AITask(greenhouse, config)
    alert_task       = AlertTask(greenhouse, config)
    persistence_task = PersistenceTask(greenhouse, config)
    api_task         = APIServerTask(greenhouse, config, db_path=config.DB_PATH)
    predict_task     = PredictiveTask(greenhouse, config)
    logger.info("[OK] 7 tasks da tao xong (HealthCheck -> APIServerTask)")

    # 3. MQTT connect
    mqtt_task.connect()
    logger.info("[OK] Dang ket noi MQTT...")

    # 4. Scheduler
    watchdog  = config.WATCHDOG_TIMEOUT if config.WATCHDOG_ENABLED else None
    scheduler = CooperativeScheduler(watchdog_timeout=watchdog)

    # FIX: Chay thuan Cooperative Multitasking voi paho-mqtt
    scheduler.register_task(
        "MQTT_Loop", mqtt_task.network_loop,
        interval=0.1, priority=9,
    )
    scheduler.register_task(
        "MoiTruong", env_task.run,
        interval=config.TASK_INTERVAL_ENVIRONMENT,  priority=8,
    )
    scheduler.register_task(
        "Bom",       pump_task.run,
        interval=config.TASK_INTERVAL_PUMP,         priority=7,
        depends_on=["MoiTruong"] # FIX: Bom phu thuoc vao Moi truong de doc sensor truoc khi dieu khien
    )
    scheduler.register_task(
        "CanhBao",   alert_task.run,
        interval=config.TASK_INTERVAL_ALERT,        priority=6,
        depends_on=["MoiTruong", "Bom"]
    )
    scheduler.register_task(
        "MQTT",      mqtt_task.run,
        interval=config.TASK_INTERVAL_MQTT,         priority=5
        # FIX: Khong phu thuoc vao task khac de dam bao telemetry/canh bao luon duoc gui di
    )
    scheduler.register_task(
        "AI",        ai_task.run,
        interval=config.TASK_INTERVAL_AI,           priority=3,
    )
    scheduler.register_task(
        "LuuTru",    persistence_task.run,
        interval=config.TASK_INTERVAL_PERSISTENCE,  priority=2,
    )
    scheduler.register_task(
        "Predict",   predict_task.run,
        interval=10.0,  priority=4,
    )
    scheduler.register_task(
        "API",       api_task.run,
        interval=config.WS_BROADCAST_INTERVAL,      priority=1,
    )

    def on_task_error(name, error):
        greenhouse.add_alert(
            f"TASK_ERROR_{name}",
            f"Task {name} bi loi: {error}",
            "CRITICAL",
        )
    scheduler.set_error_callback(on_task_error)

    logger.info("")
    logger.info(">>> Bat dau chay scheduler... (Ctrl+C de dung)")
    logger.info("")

    # 5. Run with graceful shutdown
    # FIX: Dung try/finally dam bao cleanup duoc goi ca khi co loi bat ngo
    try:
        scheduler.run(tick_interval=config.SCHEDULER_TICK)
    except KeyboardInterrupt:
        logger.info("")
        logger.info(">>> Nhan Ctrl+C - Dang dung he thong...")
    except Exception as e:
        logger.error(f">>> Loi bat ngo: {e}")
    finally:
        # Cleanup tat ca resources (goi shutdown() thong nhat theo BaseTask contract)
        scheduler.stop()
        mqtt_task.shutdown()
        persistence_task.shutdown()
        api_task.shutdown()
        
        # Luu Snapshot truoc khi thoat (qua StateManager)
        state_manager.save()
        logger.info("[OK] Da luu Snapshot (Persistence) xuong o cung")

        stats = greenhouse.get_statistics()
        logger.info("")
        logger.info("=" * 60)
        logger.info("  THONG KE PHIEN LAM VIEC")
        logger.info("=" * 60)
        logger.info(f"  Ngay mo phong:       {stats['sim_day']}")
        logger.info(f"  Thoi gian:           {greenhouse.get_sim_time_str()}")
        logger.info(f"  Lan bat/tat bom:     {stats['total_pump_cycles']}")
        logger.info(f"  Nuoc da dung:        {stats['total_water_used']} lit")
        logger.info(f"  Canh bao:            {stats['alerts_fired']}")
        logger.info(f"  Scheduler ticks:     {scheduler.tick_count}")
        logger.info("")

        for d in scheduler.get_diagnostics():
            status = "ON" if d["state"] == "RUNNING" else "OFF"
            logger.info(
                f"  [{status}] {d['name']:12s} | "
                f"Chay: {d['runs']:5d} | "
                f"Loi: {d['errors']:3d} | "
                f"Avg: {d['avg_ms']:.1f}ms"
            )

        logger.info("")
        logger.info(">>> He thong da dung. Tam biet!")


if __name__ == "__main__":
    main()

