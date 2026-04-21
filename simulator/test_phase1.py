"""Test Phase 1 - Chay scheduler offline 10 giay."""

import time
import logging
import threading
import config
from models.greenhouse import Greenhouse
from models.scheduler import CooperativeScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")

gh = Greenhouse(config)
scheduler = CooperativeScheduler(watchdog_timeout=10)


def env_task():
    gh.update_sim_time()
    s = gh.get_sensors()
    t = gh.get_sim_time_str()
    day = "[NGAY]" if gh.is_daytime() else "[DEM]"
    logger.info(
        f"[{t}] {day} | M={s['soil_moisture']}% "
        f"T={s['temperature']}C L={s['light_intensity']}lux "
        f"H={s['humidity']}% CO2={s['co2_level']}ppm"
    )


def pump_task():
    mode = gh.get_mode()
    pump = "ON" if gh.is_pump_on() else "OFF"
    logger.info(f"  [BOM] Mode={mode} | Pump={pump}")


scheduler.register_task("MoiTruong", env_task, interval=2, priority=5)
scheduler.register_task("Bom", pump_task, interval=3, priority=7)


def stop_after():
    time.sleep(10)
    scheduler.stop()
    time.sleep(0.5)

    logger.info("--- KET QUA ---")
    for d in scheduler.get_diagnostics():
        logger.info(
            f"  {d['name']}: {d['runs']} lan, "
            f"avg={d['avg_ms']}ms, loi={d['errors']}"
        )
    logger.info(f"  Ticks: {scheduler.tick_count}")
    logger.info(f"  Stats: {gh.get_statistics()}")
    logger.info(f"  Sim time: {gh.get_sim_time_str()}")
    logger.info("[OK] Phase 1 test PASSED!")


t = threading.Thread(target=stop_after, daemon=True)
t.start()
scheduler.run(tick_interval=0.1)
