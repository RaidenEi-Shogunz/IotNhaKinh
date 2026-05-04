"""
Nha Kinh Thong Minh - Task Luu Tru Du Lieu
=============================================
Luu snapshot cam bien vao SQLite database.
Tu dong don dep du lieu cu.
"""

import sqlite3
import time
import logging
import os
import threading

from tasks.base_task import BaseTask

logger = logging.getLogger("task.db")


class PersistenceTask(BaseTask):
    """Task luu du lieu cam bien vao SQLite."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self.db_path = config.DB_PATH
        self.record_count = 0
        self._conn = None
        self._db_lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        """Lay connection persistent, tao moi neu chua co hoac bi loi."""
        if self._conn is None:
            # check_same_thread=False duoc su dung vi CooperativeScheduler chay tat ca 
            # cac task tren cung mot main thread nhung co the bi hieu nham boi cac framework khac.
            # RUI RO: Neu sau nay chuyen sang multithreading that su, tinh nang nay co the
            # gay database corruption neu khong dung Lock bao ve o muc db.
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        """Tao bang va Migration."""
        with self._db_lock:
            try:
                conn = self._get_conn()
                cursor = conn.execute("PRAGMA user_version")
                version = cursor.fetchone()[0]

                if version == 0:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS sensor_data (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp REAL,
                            sim_time TEXT,
                            sim_day INTEGER,
                            soil_moisture REAL,
                            temperature REAL,
                            light_intensity REAL,
                            humidity REAL,
                            co2_level REAL,
                            pump_on INTEGER,
                            pump_duty REAL,
                            mode TEXT,
                            weather TEXT,
                            ai_status TEXT
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON sensor_data(timestamp)")
                    conn.execute("PRAGMA user_version = 1")
                    logger.info(f"[OK] Database v1 created: {self.db_path}")
                elif version >= 1:
                    # Khu vuc ap dung migrations trong tuong lai
                    pass

                conn.commit()
            except Exception as e:
                logger.error(f"[LOI] Tao database: {e}")

    def run(self):
        """Luu snapshot hien tai vao database."""
        snapshot = self.greenhouse.get_snapshot()

        with self._db_lock:
            try:
                conn = self._get_conn()
                conn.execute("""
                    INSERT INTO sensor_data (
                        timestamp, sim_time, sim_day,
                        soil_moisture, temperature, light_intensity,
                        humidity, co2_level,
                        pump_on, pump_duty, mode, weather, ai_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    time.time(),
                    snapshot["sim_time"],
                    snapshot["sim_day"],
                    snapshot["soil_moisture"],
                    snapshot["temperature"],
                    snapshot["light_intensity"],
                    snapshot["humidity"],
                    snapshot["co2_level"],
                    1 if snapshot["pump_on"] else 0,
                    snapshot["pump_duty"],
                    snapshot["mode"],
                    snapshot["weather"],
                    snapshot["ai_status"],
                ))
                conn.commit()

                self.record_count += 1

                # Don dep du lieu cu
                if self.record_count % 100 == 0:
                    self._cleanup(conn)

            except Exception as e:
                # Reset connection neu bi loi
                self._conn = None
                logger.error(f"[LOI] Luu database: {e}")

    def _cleanup(self, conn):
        """Xoa du lieu cu neu vuot gioi han."""
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM sensor_data")
            count = cursor.fetchone()[0]

            if count > self.config.DB_MAX_RECORDS:
                delete_count = self.config.DB_CLEANUP_BATCH
                # xoa duoc dung so luong du cho ID bi non-contiguous.
                conn.execute(f"""
                    DELETE FROM sensor_data
                    WHERE id IN (
                        SELECT id FROM sensor_data
                        ORDER BY id ASC
                        LIMIT {delete_count}
                    )
                """)
                conn.commit()
                logger.info(f"  [DB] Don dep: xoa {delete_count} ban ghi cu")
        except Exception as e:
            logger.error(f"  [LOI] Don dep DB: {e}")

    def shutdown(self):
        """Dong ket noi DB khi dung he thong."""
        if self._conn:
            try:
                self._conn.close()
                logger.info("[OK] Da dong ket noi database")
            except Exception:
                pass
            self._conn = None
