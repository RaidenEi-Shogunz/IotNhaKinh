"""
Nha Kinh Thong Minh - Task Giao Tiep MQTT
============================================
Publish du lieu cam bien, subscribe lenh dieu khien.

FIX [1]: Rate limiter chinh xac - dem tung publish, cho neu vuot 30/phut
FIX [2]: offline_queue flush co delay giua cac tin tranh burst
FIX [3]: Publish watering-event khi bom thay doi trang thai
FIX [4]: Them sim_time, sim_day vao AI payload de dashboard dong bo dong ho
FIX [5]: _on_disconnect log ro reason_code de de debug
FIX [6]: PID display - publish pid_output va pid_setpoint len feed ai-status
"""

import json
import time
import logging
from collections import deque
import paho.mqtt.client as mqtt

logger = logging.getLogger("task.mqtt")

# Adafruit IO free: 30 points/phut = 1 point / 2 giay
_AIO_RATE_LIMIT   = 30          # points per minute
_AIO_RATE_WINDOW  = 60.0        # giay


class MQTTTask:
    """Task quan ly giao tiep MQTT voi Adafruit IO."""

    def __init__(self, greenhouse, config):
        self.greenhouse    = greenhouse
        self.config        = config
        self.connected     = False
        self.last_publish  = 0
        self.publish_count = 0

        # Sliding window dem so lan publish trong 60 giay qua
        self._publish_times = deque()

        # Offline queue: luu khi chua ket noi
        self.offline_queue = deque(maxlen=50)

        # Theo doi trang thai bom
        self._last_pump_state = False
        self._last_alert_count = 0

        # paho-mqtt v2 API
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(config.ADAFRUIT_USERNAME, config.ADAFRUIT_KEY)
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message

        # Last Will Testament - bao hieu offline khi mat ket noi dot ngot
        lwt_topic = config.get_topic(config.FEED_PUMP_STATUS)
        self.client.will_set(lwt_topic, "OFFLINE", qos=0, retain=False)

    # ------------------------------------------------------------------
    # Ket noi
    # ------------------------------------------------------------------
    def connect(self):
        cfg = self.config
        try:
            logger.info(f"Dang ket noi {cfg.MQTT_HOST}:{cfg.MQTT_PORT}...")
            self.client.connect(cfg.MQTT_HOST, cfg.MQTT_PORT, cfg.MQTT_KEEPALIVE)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Loi ket noi MQTT: {e}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        cfg = self.config
        if reason_code == 0:
            self.connected = True
            logger.info("[OK] Da ket noi MQTT broker!")
            for feed in [cfg.FEED_PUMP_CMD, cfg.FEED_MODE, cfg.FEED_THRESHOLD]:
                topic = cfg.get_topic(feed)
                client.subscribe(topic, qos=0)   # FIX: QoS 0 giam overhead
                logger.info(f"  [SUB] {topic}")

            # FIX: Flush offline queue voi delay nho tranh burst
            self._flush_offline_queue()
        else:
            logger.error(f"[LOI] Ket noi that bai - reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        # FIX: Log ro reason_code de de debug
        if reason_code == 0:
            logger.info("Da ngat ket noi MQTT (chu dong)")
        elif reason_code == 141:
            logger.warning(
                "[LOI] Adafruit IO ngat ket noi - co the vuot rate limit (rc=141)! "
                "Kiem tra lai RATE_LIMIT_MIN_INTERVAL trong config.py"
            )
        else:
            logger.warning(f"Mat ket noi MQTT (rc={reason_code}), dang thu ket noi lai...")

    def _on_message(self, client, userdata, msg):
        cfg     = self.config
        topic   = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        logger.info(f"  [NHAN] {topic} = {payload}")

        try:
            feed = topic.split("/feeds/")[-1] if "/feeds/" in topic else topic

            if feed == cfg.FEED_PUMP_CMD:
                if payload.upper() == "ON":
                    self.greenhouse.set_pump(True, trigger="MANUAL")
                    logger.info("  [LENH] Bat bom (MANUAL)")
                elif payload.upper() == "OFF":
                    self.greenhouse.set_pump(False, trigger="MANUAL")
                    logger.info("  [LENH] Tat bom (MANUAL)")

            elif feed == cfg.FEED_MODE:
                mode = payload.upper()
                if mode in ("AUTO", "MANUAL"):
                    self.greenhouse.set_mode(mode)
                    logger.info(f"  [LENH] Chuyen che do: {mode}")

            elif feed == cfg.FEED_THRESHOLD:
                try:
                    val = float(payload)
                    self.greenhouse.set_threshold(val)
                    self.greenhouse.set_pid_setpoint(val)
                    logger.info(f"  [LENH] Nguong moi: {val}%")
                except ValueError:
                    logger.warning(f"  [LOI] Nguong khong hop le: {payload}")
        except Exception as e:
            logger.error(f"  [LOI] Xu ly lenh: {e}")

    # ------------------------------------------------------------------
    # Rate limiting chinh xac (sliding window)
    # ------------------------------------------------------------------
    def _can_publish(self):
        """Kiem tra con trong room de publish trong cua so 60 giay."""
        now = time.time()
        cutoff = now - _AIO_RATE_WINDOW
        # Xoa cac timestamp cu
        while self._publish_times and self._publish_times[0] < cutoff:
            self._publish_times.popleft()
        return len(self._publish_times) < _AIO_RATE_LIMIT

    def _record_publish(self):
        self._publish_times.append(time.time())

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------
    def _safe_publish(self, topic, payload, qos=0):
        """
        Publish 1 tin. Neu chua ket noi -> queue.
        Neu vuot rate limit -> queue.
        """
        if not self.connected:
            self.offline_queue.append((topic, payload))
            logger.debug(f"  [QUEUE] offline: {topic} (size={len(self.offline_queue)})")
            return False

        if not self._can_publish():
            logger.warning(
                f"  [RATE] Vuot rate limit! Bo qua: {topic}. "
                f"Tang RATE_LIMIT_MIN_INTERVAL trong config.py"
            )
            return False

        self.client.publish(topic, payload, qos=qos)
        self._record_publish()
        return True

    def _flush_offline_queue(self):
        """
        FIX: Flush offline queue voi khoang cach 0.2s giua cac tin
        tranh burst 7 tin cung luc lam Adafruit IO ngat ket noi.
        """
        flushed = 0
        while self.offline_queue:
            if not self._can_publish():
                logger.warning(f"  [QUEUE] Dung flush - con {len(self.offline_queue)} tin cho rate limit")
                break
            topic, payload = self.offline_queue.popleft()
            self.client.publish(topic, payload, qos=0)
            self._record_publish()
            flushed += 1
            time.sleep(0.25)  # FIX: 250ms gap tranh burst
        if flushed:
            logger.info(f"  [QUEUE] Da flush {flushed} tin offline")

    # ------------------------------------------------------------------
    # Task chinh
    # ------------------------------------------------------------------
    def run(self):
        cfg = self.config
        now = time.time()

        # 1. Kiem tra thay doi trang thai bom -> publish watering-event ngay
        current_pump = self.greenhouse.is_pump_on()
        if current_pump != self._last_pump_state:
            self._last_pump_state = current_pump
            event = self.greenhouse.get_latest_watering_event()
            if event:
                self._safe_publish(
                    cfg.get_topic(cfg.FEED_WATERING_EVENT),
                    json.dumps(event, ensure_ascii=False),
                )
                logger.info(
                    f"  [EVENT] Bom {event['action']} | "
                    f"M={event['moisture']}% | trigger={event['trigger']}"
                )

        # 2. Publish alert moi (neu co)
        self._publish_new_alerts()

        # 3. Rate limiter cho publish dinh ky
        if (now - self.last_publish) < cfg.RATE_LIMIT_MIN_INTERVAL:
            return

        sensors  = self.greenhouse.get_sensors()
        sim_time = self.greenhouse.get_sim_time_str()
        pid      = self.greenhouse.get_pid_state()

        try:
            # FIX: Gom tat ca 9 feeds, publish tung cai voi kiem tra rate
            feeds_to_publish = [
                (cfg.FEED_SOIL_MOISTURE, str(sensors["soil_moisture"])),
                (cfg.FEED_TEMPERATURE,   str(sensors["temperature"])),
                (cfg.FEED_LIGHT,         str(sensors["light_intensity"])),
                (cfg.FEED_HUMIDITY,      str(sensors["humidity"])),
                (cfg.FEED_CO2,           str(sensors["co2_level"])),
                (cfg.FEED_PUMP_STATUS,   "ON" if self.greenhouse.is_pump_on() else "OFF"),
            ]

            # AI payload: gom ca sim_time, sim_day, pid de dashboard hien thi day du
            ai = self.greenhouse.get_ai_status()
            ai["sim_time"]      = sim_time
            ai["sim_day"]       = self.greenhouse.get_sim_day()
            ai["pid_output"]    = round(pid["output"], 1)    # FIX: PID cho dashboard
            ai["pid_setpoint"]  = round(pid["setpoint"], 1)
            feeds_to_publish.append((cfg.FEED_AI_STATUS, json.dumps(ai, ensure_ascii=False)))

            published = 0
            for feed_name, payload in feeds_to_publish:
                if self._safe_publish(cfg.get_topic(feed_name), payload):
                    published += 1
                else:
                    break   # Neu bi rate limit, dung lai - chu ky sau tiep tuc

            if published > 0:
                self.last_publish  = now
                self.publish_count += 1
                pump_str = "ON" if self.greenhouse.is_pump_on() else "OFF"
                logger.info(
                    f"  [GUI] {published}/7 feeds | #{self.publish_count} | "
                    f"M={sensors['soil_moisture']}% "
                    f"T={sensors['temperature']}C "
                    f"Pump={pump_str} "
                    f"SimTime={sim_time}"
                )

        except Exception as e:
            logger.error(f"  [LOI] Publish: {e}")

    def _publish_new_alerts(self):
        cfg   = self.config
        stats = self.greenhouse.get_statistics()
        count = stats["alerts_fired"]

        if count > self._last_alert_count:
            diff   = count - self._last_alert_count
            recent = self.greenhouse.get_recent_alerts(count=diff)
            self._last_alert_count = count
            for alert in recent:
                self._safe_publish(
                    cfg.get_topic(cfg.FEED_ALERT),
                    json.dumps(alert, ensure_ascii=False),
                )
                logger.info(f"  [ALERT] [{alert['severity']}] {alert['message']}")

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("[OK] Da ngat ket noi MQTT")
        except Exception:
            pass
