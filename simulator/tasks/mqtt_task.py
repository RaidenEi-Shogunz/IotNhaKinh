"""
Nha Kinh Thong Minh - Task Giao Tiep MQTT
============================================
NANG CAP v5.0 - Batch Publish:
  [1] Gom 6 sensor feeds + pump_status -> 1 JSON tren feed "sensor-data"
      Tiet kiem: 9 data points/cycle -> 2 data points/cycle
      Con lai ~28 points/phut cho alerts va events (tu 5.5 len 28)
  [2] RATE_LIMIT_MIN_INTERVAL: 22s -> 5s (an toan vi chi con 2 feeds/cycle)
  [3] Dashboard: them handler cho feed "sensor-data" JSON
  [4] Giu nguyen: Token Bucket, offline queue TTL, LWT, QoS 1 cho cmd feeds
  [5] Backward compat: FEED_PUMP_STATUS van dung cho LWT

NANG CAP v3.0 (giu nguyen):
  [1] Thong nhat giao thuc: dung MQTTv311 (Adafruit IO khong ho tro v5)
  [2] offline_queue: ghi chu ro ve security (payload khong nhay cam)
  [3] Exponential backoff chinh xac tu paho (reconnect_delay_set da co)
  [4] Giu nguyen: Token Bucket, offline queue TTL, LWT, QoS 1 cho cmd feeds
"""

import os
import json
import time
import logging
import threading
from collections import deque
from typing import Deque, Tuple, Dict, Any, List
import paho.mqtt.client as mqtt

from tasks.base_task import BaseTask

logger = logging.getLogger("task.mqtt")

_AIO_RATE_LIMIT  = 30
_AIO_RATE_WINDOW = 60.0
_OFFLINE_TTL     = 3600.0


class MQTTTask(BaseTask):
    """Task quan ly giao tiep MQTT voi Adafruit IO."""

    def __init__(self, greenhouse: Any, config: Any) -> None:
        self.greenhouse    = greenhouse
        self.config        = config
        self._connected     = False
        self._lock         = threading.Lock() # Mutex de chong Race Condition voi paho background thread
        self.last_publish  = 0.0
        self.publish_count = 0

        # Token Bucket
        self._tokens: float           = _AIO_RATE_LIMIT
        self._last_token_update: float = time.time()
        self._token_rate: float        = _AIO_RATE_LIMIT / _AIO_RATE_WINDOW
        self._last_publish_ts: float   = 0.0

        # Queues
        self.offline_queue_file = "offline_queue.json"
        self.offline_queue: Deque[Tuple[str, str, float]] = deque(maxlen=1000)
        self.publish_queue: Deque[Tuple[str, str]]        = deque(maxlen=1000) # FIX Bug An 14: Tang buffer cho rate limiter, tranh bi drop khi bi block
        self._load_offline_queue()

        # Deduplication state
        stats = self.greenhouse.get_statistics()
        self._last_alert_count    = stats.get("alerts_fired", 0)
        self._last_watering_count = stats.get("watering_events_count", 0)

        # paho-mqtt client (MQTTv5, persistent session)
        client_id = f"gh_sim_{config.ADAFRUIT_USERNAME}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311, # FIX: Adafruit IO khong the chay MQTTv5 on port 8883
        )
        if config.MQTT_PORT == 8883:
            self.client.tls_set()
        self.client.username_pw_set(config.ADAFRUIT_USERNAME, config.ADAFRUIT_KEY)
        # Exponential backoff: 1s -> 120s
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message

        # Last Will Testament
        lwt_topic = config.get_topic(config.FEED_PUMP_STATUS)
        self.client.will_set(lwt_topic, "OFFLINE", qos=0, retain=False)

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        with self._lock:
            self._connected = value

    # ------------------------------------------------------------------
    # Offline Queue Persistence
    # ------------------------------------------------------------------
    def _load_offline_queue(self) -> None:
        if not os.path.exists(self.offline_queue_file):
            return
        try:
            # FIX Bug An 2: Doc file I/O ben ngoai Lock de khong block thread
            with open(self.offline_queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            now = time.time()
            loaded = expired = 0
            
            # Chi dung Lock khi thao tac voi cau truc du lieu Memory
            with self._lock:
                for item in data:
                    ts = item[2] if len(item) > 2 else 0
                    if (now - ts) < _OFFLINE_TTL:
                        self.offline_queue.append((item[0], item[1], ts))
                        loaded += 1
                    else:
                        expired += 1
                        
            if expired:
                logger.info(f"  [QUEUE] Loai bo {expired} tin cu (TTL > {_OFFLINE_TTL}s)")
            if loaded:
                logger.info(f"  [QUEUE] Nap lai {loaded} tin tu offline queue")
        except Exception as e:
            logger.error(f"Loi doc offline queue: {e}")

    def _save_offline_queue(self) -> None:
        try:
            # Atomic write: tmp -> replace
            tmp = self.offline_queue_file + ".tmp"
            with self._lock:
                queue_snapshot = list(self.offline_queue)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(queue_snapshot, f, ensure_ascii=False)
            os.replace(tmp, self.offline_queue_file)
        except Exception as e:
            logger.error(f"Loi luu offline queue: {e}")

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------
    def connect(self) -> None:
        cfg = self.config
        try:
            logger.info(f"Dang ket noi {cfg.MQTT_HOST}:{cfg.MQTT_PORT} (MQTTv5) bang Background Thread...")
            # FIX: Dung connect_async de khong bi block Cooperative Scheduler
            self.client.connect_async(cfg.MQTT_HOST, cfg.MQTT_PORT, cfg.MQTT_KEEPALIVE,
                                      clean_start=False)
            # FIX: Dung loop_start() de chay background thread xu ly TCP/Socket rieng
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Loi ket noi MQTT: {e}")

    def network_loop(self) -> None:
        """
        Da chuyen TCP IO sang loop_start() background thread.
        Task nay trong Cooperative Scheduler hien gio chi xu ly hang doi (queue)
        de publish tin nhan mot cach nhe nhang nhat, khong so block socket.
        """
        self._process_queues()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        cfg = self.config
        if reason_code == 0:
            self.connected = True
            logger.info("[OK] Da ket noi MQTT broker!")
            for feed in [cfg.FEED_PUMP_CMD, cfg.FEED_MODE, cfg.FEED_THRESHOLD, cfg.FEED_AI_CMD]:
                topic = cfg.get_topic(feed)
                client.subscribe(topic, qos=1)
                logger.info(f"  [SUB] {topic}")
            self._process_queues()
        else:
            logger.error(f"[LOI] Ket noi that bai - reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected = False
        if reason_code == 0:
            logger.info("Da ngat ket noi MQTT (chu dong)")
        elif reason_code == 141:
            logger.warning(
                "[LOI] Adafruit IO ngat ket noi - co the vuot rate limit (rc=141)! "
                "Kiem tra RATE_LIMIT_MIN_INTERVAL trong config.py"
            )
        else:
            logger.warning(f"Mat ket noi MQTT (rc={reason_code}), dang thu lai...")

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        cfg     = self.config
        topic   = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        logger.info(f"  [NHAN] {topic} = {payload}")

        try:
            feed = topic.split("/feeds/")[-1] if "/feeds/" in topic else topic

            if feed == cfg.FEED_PUMP_CMD:
                cmd = payload.upper()
                if self.greenhouse.get_mode() == "AUTO":
                    logger.warning(f"  [MQTT] Tu choi lenh '{cmd}' vi he thong dang o che do AUTO")
                else:
                    if cmd == "ON":
                        self.greenhouse.set_pump(True, trigger="MANUAL")
                    elif cmd == "OFF":
                        self.greenhouse.set_pump(False, trigger="MANUAL")
                    else:
                        logger.warning(f"  [LOI] Lenh bom khong hop le: '{payload}'")

            elif feed == cfg.FEED_MODE:
                mode = payload.upper()
                if mode in ("AUTO", "MANUAL"):
                    self.greenhouse.set_mode(mode)
                    logger.info(f"  [LENH] Chuyen che do: {mode}")
                else:
                    logger.warning(f"  [LOI] Che do khong hop le: '{payload}'")

            elif feed == cfg.FEED_THRESHOLD:
                try:
                    val = float(payload)
                    if val < 10 or val > 80:
                        logger.warning(
                            f"  [LOI] Nguong {val}% ngoai pham vi (10-80%). "
                            f"Se bi clamp ve {max(10, min(80, int(val)))}%"
                        )
                    self.greenhouse.set_threshold(val)
                    self.greenhouse.set_pid_setpoint(val)
                    actual = self.greenhouse.get_threshold()
                    logger.info(f"  [LENH] Nguong moi: {actual}%")
                except ValueError:
                    logger.warning(f"  [LOI] Nguong khong phai so: '{payload}'")
            
            elif feed == cfg.FEED_AI_CMD:
                try:
                    res = json.loads(payload)
                    self.greenhouse.set_ai_camera_result(res)
                    logger.info(f"  [AI CAM] Nhận kết quả từ Teachable Machine: {res}")
                except Exception as e:
                    logger.warning(f"  [LOI] Payload AI Camera không hợp lệ: {e}")

        except Exception as e:
            logger.error(f"  [LOI] Xu ly lenh: {e}")

    # ------------------------------------------------------------------
    # Rate Limiting (Token Bucket)
    # ------------------------------------------------------------------
    def _can_publish_internal(self) -> bool:
        now = time.time()
        # Burst guard: cach nhau toi thieu 1.5s
        if now - self._last_publish_ts < 1.5:
            return False
        elapsed = now - self._last_token_update
        self._tokens += elapsed * self._token_rate
        if self._tokens > _AIO_RATE_LIMIT:
            self._tokens = _AIO_RATE_LIMIT
        self._last_token_update = now
        return self._tokens >= 1.0

    def _record_publish_internal(self) -> None:
        self._tokens -= 1.0
        self._last_publish_ts = time.time()

    # ------------------------------------------------------------------
    # Queue Processing
    # ------------------------------------------------------------------
    def _process_queues(self) -> None:
        count_expired = 0
        now = time.time()

        while self.connected:
            with self._lock:
                if not self.publish_queue or not self._can_publish_internal():
                    break
                topic, payload = self.publish_queue.popleft()
                self._record_publish_internal()
            self.client.publish(topic, payload, qos=0)

        while self.connected:
            with self._lock:
                if not self.offline_queue or not self._can_publish_internal():
                    break
                topic, payload, ts = self.offline_queue.popleft()
                self._record_publish_internal()
                
            if (now - ts) > _OFFLINE_TTL:
                count_expired += 1
                continue
            qos = 1 if ("alert" in topic or "watering" in topic) else 0
            self.client.publish(topic, payload, qos=qos)

        if count_expired:
            logger.info(f"  [QUEUE] Loai bo {count_expired} tin het han (TTL)")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------
    def run(self) -> None:
        cfg = self.config
        now = time.time()

        # 1. Watering events
        stats   = self.greenhouse.get_statistics()
        w_count = stats.get("watering_events_count", 0)
        if w_count > self._last_watering_count:
            diff        = w_count - self._last_watering_count
            recent_logs = self.greenhouse.get_watering_log(count=min(diff, 20))
            self._last_watering_count = w_count
            for event in recent_logs:
                topic   = cfg.get_topic(cfg.FEED_WATERING_EVENT)
                payload = json.dumps(event, ensure_ascii=False)
                if not self.connected:
                    with self._lock:
                        self.offline_queue.append((topic, payload, time.time()))
                    self._save_offline_queue()
                else:
                    with self._lock:
                        self.publish_queue.append((topic, payload))
                logger.info(
                    f"  [EVENT] Bom {event['action']} | "
                    f"M={event['moisture']}% | trigger={event['trigger']}"
                )

        # 2. Alerts
        self._publish_new_alerts()

        # 3. Rate-limited periodic publish
        if (now - self.last_publish) < (cfg.RATE_LIMIT_MIN_INTERVAL - 1.0):
            return

        sensors  = self.greenhouse.get_sensors()
        sim_time = self.greenhouse.get_sim_time_str()
        pid      = self.greenhouse.get_pid_state()

        try:
            # --- BATCH PUBLISH: gom tat ca sensor vao 1 JSON ---
            # Truoc v5.0: 7 feeds rieng le = 7 data points/cycle
            # Sau  v5.0: 1 feed sensor-data + 1 feed ai-status = 2 data points/cycle
            sensor_batch = {
                "soil_moisture":   round(sensors["soil_moisture"],   2),
                "temperature":     round(sensors["temperature"],     2),
                "light_intensity": round(sensors["light_intensity"], 1),
                "humidity":        round(sensors["humidity"],        2),
                "co2_level":       round(sensors["co2_level"],      1),
                "ec_level":        round(sensors["ec_level"],       3),
                "ph_level":        round(sensors["ph_level"],       2),
                "pump_status":     "ON" if self.greenhouse.is_pump_on() else "OFF",
                "ts":              int(now),
            }

            ai = self.greenhouse.get_ai_status()
            ai["sim_time"]          = sim_time
            ai["sim_day"]           = self.greenhouse.get_sim_day()
            ai["pid_output"]        = round(pid["output"],   1)
            ai["pid_setpoint"]      = round(pid["setpoint"], 1)
            ai["weather_condition"] = self.greenhouse.get_weather()["condition"]

            feeds_to_publish = [
                (cfg.FEED_SENSOR_DATA, json.dumps(sensor_batch, ensure_ascii=False)),
                (cfg.FEED_AI_STATUS,   json.dumps(ai,           ensure_ascii=False)),
            ]

            for feed_name, payload in feeds_to_publish:
                topic = cfg.get_topic(feed_name)
                with self._lock:
                    if not self._connected:
                        self.offline_queue.append((topic, payload, time.time()))
                    else:
                        self.publish_queue.append((topic, payload))

            if not self.connected:
                self._save_offline_queue()

            self.last_publish  = now
            self.publish_count += 1
            pump_str = "ON" if self.greenhouse.is_pump_on() else "OFF"
            logger.info(
                f"  [GUI] Queued {len(feeds_to_publish)} feeds | #{self.publish_count} | "
                f"M={sensors['soil_moisture']}% T={sensors['temperature']}C "
                f"EC={sensors['ec_level']}mS pH={sensors['ph_level']} "
                f"Pump={pump_str} SimTime={sim_time}"
            )
        except Exception as e:
            logger.error(f"  [LOI] Publish: {e}")

    def _publish_new_alerts(self) -> None:
        cfg   = self.config
        stats = self.greenhouse.get_statistics()
        count = stats["alerts_fired"]
        if count > self._last_alert_count:
            diff   = count - self._last_alert_count
            recent = self.greenhouse.get_recent_alerts(count=min(diff, 10))
            self._last_alert_count = count
            for alert in recent:
                topic   = cfg.get_topic(cfg.FEED_ALERT)
                payload = json.dumps(alert, ensure_ascii=False)
                if not self.connected:
                    with self._lock:
                        self.offline_queue.append((topic, payload, time.time()))
                    self._save_offline_queue()
                else:
                    with self._lock:
                        self.publish_queue.append((topic, payload))
                logger.info(f"  [ALERT] [{alert['severity']}] {alert['message']}")

    def shutdown(self) -> None:
        try:
            self.client.loop_stop() # FIX: Dung background thread cua paho
            self.client.disconnect()
            logger.info("[OK] Da ngat ket noi MQTT va dung background thread")
        except Exception:
            pass
