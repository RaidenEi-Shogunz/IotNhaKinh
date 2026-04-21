"""
Nha Kinh Thong Minh - Cooperative Scheduler
=============================================
Bo lap lich hop tac (cooperative) quan ly cac task
theo mo hinh RTOS don gian.

Nguyen tac:
- Moi tick, scheduler kiem tra task nao da den han.
- Chay theo thu tu priority (cao truoc).
- Moi task PHAI tra quyen dieu khien (khong block).
- Co watchdog timer phat hien task bi treo.
- Tu dong disable task khi loi lien tiep.
"""

import time
import logging
import threading
from typing import List, Optional, Callable, Any

logger = logging.getLogger("scheduler")


class TaskInfo:
    """Thong tin mot task dang ky."""

    def __init__(self, name: str, callback: Callable[[], Any], interval: float, priority: int) -> None:
        self.name: str = name
        self.callback: Callable[[], Any] = callback
        self.interval: float = interval       # Giay giua cac lan chay
        self.priority: int = priority       # Cao hon = chay truoc
        self.enabled: bool = True
        self.last_run: float = 0.0
        self.run_count: int = 0
        self.error_count: int = 0
        self.consecutive_errors: int = 0
        self.last_error: Optional[str] = None
        self.total_exec_time: float = 0.0
        self.max_exec_time: float = 0.0

    def avg_exec_time_ms(self):
        if self.run_count == 0:
            return 0.0
        return (self.total_exec_time / self.run_count) * 1000


class CooperativeScheduler:
    """
    Bo lap lich hop tac quan ly thuc thi cac task.
    Ho tro: priority, watchdog, health monitoring, event callbacks.
    """

    def __init__(self, watchdog_timeout: Optional[float] = None) -> None:
        self._tasks: List[TaskInfo] = []
        self._running: bool = False
        self._tick_count: int = 0
        self._watchdog_timeout: Optional[float] = watchdog_timeout
        self._on_error_callback: Optional[Callable[[str, Exception], Any]] = None
        self._lock = threading.Lock()

    def register_task(self, name: str, callback: Callable[[], Any], interval: float, priority: int = 5) -> None:
        """Dang ky task moi."""
        task = TaskInfo(name, callback, interval, priority)
        self._tasks.append(task)
        # Sap xep theo priority giam dan
        self._tasks.sort(key=lambda t: t.priority, reverse=True)
        logger.info(f"  [+] Task '{name}' | interval={interval}s | priority={priority}")

    def set_error_callback(self, callback: Callable[[str, Exception], Any]) -> None:
        """Dat ham goi khi co loi."""
        self._on_error_callback = callback

    def run(self, tick_interval: float = 0.1) -> None:
        """Vong lap chinh cua scheduler."""
        self._running = True
        logger.info(f"Scheduler bat dau | {len(self._tasks)} tasks | tick={tick_interval}s")

        while self._running:
            self._tick_count += 1
            now = time.time()

            for task in self._tasks:
                if not task.enabled:
                    continue

                # Kiem tra da den han chua
                if (now - task.last_run) < task.interval:
                    continue

                # Chay task
                start = time.time()
                try:
                    task.callback()
                    elapsed = time.time() - start

                    task.run_count += 1
                    task.last_run = now
                    task.consecutive_errors = 0
                    task.total_exec_time += elapsed

                    if elapsed > task.max_exec_time:
                        task.max_exec_time = elapsed

                    # Watchdog: canh bao neu task chay qua lau
                    if self._watchdog_timeout and elapsed > self._watchdog_timeout:
                        logger.warning(
                            f"[WATCHDOG] Task '{task.name}' chay {elapsed:.1f}s "
                            f"> timeout {self._watchdog_timeout}s"
                        )

                except Exception as e:
                    elapsed = time.time() - start
                    task.error_count += 1
                    task.consecutive_errors += 1
                    task.last_error = str(e)
                    task.last_run = now

                    logger.error(f"[LOI] Task '{task.name}': {e}")

                    # Goi callback loi
                    if self._on_error_callback:
                        try:
                            self._on_error_callback(task.name, e)
                        except Exception:
                            pass

                    # Tu dong disable neu loi lien tiep qua nhieu
                    if task.consecutive_errors >= 5:
                        task.enabled = False
                        logger.error(
                            f"[DISABLED] Task '{task.name}' bi tat "
                            f"sau {task.consecutive_errors} loi lien tiep"
                        )

            time.sleep(tick_interval)

    def stop(self) -> None:
        """Dung scheduler."""
        self._running = False
        logger.info("Scheduler dang dung...")

    def get_diagnostics(self) -> List[dict]:
        """Tra ve thong tin chan doan cua tat ca tasks."""
        result = []
        for t in self._tasks:
            result.append({
                "name": t.name,
                "enabled": t.enabled,
                "runs": t.run_count,
                "errors": t.error_count,
                "avg_ms": round(t.avg_exec_time_ms(), 2),
                "max_ms": round(t.max_exec_time * 1000, 2),
                "last_error": t.last_error,
            })
        return result

    @property
    def tick_count(self):
        return self._tick_count

    @property
    def task_count(self):
        return len(self._tasks)
