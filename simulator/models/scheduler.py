"""
Nha Kinh Thong Minh - Cooperative Scheduler
=============================================
  [1] Dependency enforcement that su: dependency bi PAUSED -> skip task phu thuoc
  [2] _sort_tasks chi rebuild khi can (O(n) check truoc)
  [3] DummyLock co canh bao ro rang neu duoc dung voi thread that
  [4] Generator preemption chinh xac
  [5] Watchdog, auto-pause sau N loi, diagnostic day du
"""

import time
import logging
from typing import List, Optional, Callable, Any, Dict, Set

logger = logging.getLogger("scheduler")


class TaskInfo:
    """Thong tin mot task dang ky."""

    def __init__(
        self,
        name: str,
        callback: Callable[[], Any],
        interval: float,
        priority: int,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        self.name: str = name
        self.callback: Callable[[], Any] = callback
        self.interval: float = interval
        self.priority: int = priority
        self.depends_on: List[str] = depends_on or []
        self.state: str = "INIT"
        self.last_run: float = 0.0
        self.run_count: int = 0
        self.error_count: int = 0
        self.consecutive_errors: int = 0
        self.last_error: Optional[str] = None
        self.total_exec_time: float = 0.0
        self.max_exec_time: float = 0.0
        self.generator = None

    def avg_exec_time_ms(self) -> float:
        if self.run_count == 0:
            return 0.0
        return (self.total_exec_time / self.run_count) * 1000

    def set_priority(self, new_priority: int) -> None:
        self.priority = new_priority


class CooperativeScheduler:
    """
    Bo lap lich hop tac quan ly thuc thi cac task.
    Ho tro: priority, dependency enforcement, watchdog, health monitoring.

          - Dependency enforcement that su: neu dependency PAUSED/STOPPED -> skip
      - _sort_tasks chi chay lai khi danh sach thay doi
      - Error isolation ro rang
    """

    MAX_CONSECUTIVE_ERRORS = 5

    def __init__(self, watchdog_timeout: Optional[float] = None) -> None:
        self._tasks: List[TaskInfo] = []
        self._running: bool = False
        self._tick_count: int = 0
        self._watchdog_timeout: Optional[float] = watchdog_timeout
        self._on_error_callback: Optional[Callable[[str, Exception], Any]] = None
        self._sorted = True  # Flag de tranh rebuild khong can thiet
        
        self._last_tick_time: float = time.time()
        self._watchdog_thread: Optional[Any] = None

    def _watchdog_loop(self) -> None:
        import os
        import signal
        while self._running:
            time.sleep(1.0)
            if self._watchdog_timeout and self._running:
                if (time.time() - self._last_tick_time) > self._watchdog_timeout:
                    logger.critical(f"[WATCHDOG] SYSTEM HANG! Scheduler bi block tren {self._watchdog_timeout}s. Force kill (SIGINT)!")
                    os.kill(os.getpid(), signal.SIGINT)
                    break

    # ------------------------------------------------------------------
    # Topological Sort (Dependency Graph)
    # ------------------------------------------------------------------
    def _sort_tasks(self) -> None:
        """
        Sap xep task theo dependency graph (topological sort),
        sau do theo priority khi khong co rang buoc thu tu.

                """
        if self._sorted:
            return

        visited: Set[str] = set()
        temp_mark: Set[str] = set()
        order: List[str] = []
        task_dict = {t.name: t for t in self._tasks}

        def visit(n: str) -> None:
            if n in temp_mark:
                logger.error(f"[!] Circular dependency phat hien tai task '{n}'")
                return
            if n not in visited:
                temp_mark.add(n)
                if n in task_dict:
                    # Duyet dependency theo thu tu priority giam dan (on dinh)
                    deps = sorted(
                        task_dict[n].depends_on,
                        key=lambda d: task_dict[d].priority if d in task_dict else 0,
                        reverse=True,
                    )
                    for m in deps:
                        visit(m)
                temp_mark.discard(n)
                visited.add(n)
                order.append(n)

        for t in sorted(self._tasks, key=lambda t: t.priority, reverse=True):
            visit(t.name)

        self._tasks = [task_dict[n] for n in order if n in task_dict]
        self._sorted = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register_task(
        self,
        name: str,
        callback: Callable[[], Any],
        interval: float,
        priority: int = 5,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        """Dang ky task moi voi dependencies."""
        if hasattr(callback, "__self__"):
            from tasks.base_task import BaseTask
            if not isinstance(callback.__self__, BaseTask):
                logger.warning(
                    f"  [!] Task '{name}' khong ke thua BaseTask - "
                    f"vi pham interface contract"
                )
        task = TaskInfo(name, callback, interval, priority, depends_on)
        task.state = "RUNNING"
        self._tasks.append(task)
        self._sorted = False
        self._sort_tasks()
        logger.info(
            f"  [+] Task '{name}' | interval={interval}s | "
            f"priority={priority} | deps={task.depends_on}"
        )

    def unregister_task(self, name: str) -> bool:
        """Huy dang ky mot task."""
        for i, t in enumerate(self._tasks):
            if t.name == name:
                t.state = "STOPPED"
                del self._tasks[i]
                self._sorted = False
                logger.info(f"  [-] Task '{name}' unregistered.")
                return True
        return False

    def pause_task(self, name: str) -> bool:
        """Tam dung mot task."""
        for t in self._tasks:
            if t.name == name and t.state == "RUNNING":
                t.state = "PAUSED"
                logger.info(f"  [||] Task '{name}' paused.")
                return True
        return False

    def resume_task(self, name: str) -> bool:
        """Tiep tuc mot task da tam dung."""
        for t in self._tasks:
            if t.name == name and t.state == "PAUSED":
                t.state = "RUNNING"
                logger.info(f"  [>] Task '{name}' resumed.")
                return True
        return False

    def set_priority(self, name: str, priority: int) -> bool:
        """Thay doi priority tai runtime."""
        for t in self._tasks:
            if t.name == name:
                t.set_priority(priority)
                self._sorted = False
                self._sort_tasks()
                logger.info(f"  [PRIORITY] Task '{name}' changed to {priority}")
                return True
        return False

    def set_error_callback(
        self, callback: Callable[[str, Exception], Any]
    ) -> None:
        self._on_error_callback = callback

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(
        self, tick_interval: float = 0.1, max_ticks: Optional[int] = None
    ) -> None:
        """Vong lap chinh cua scheduler."""
        self._running = True
        self._sort_tasks()  # Dam bao sap xep truoc khi chay
        logger.info(
            f"Scheduler bat dau | {len(self._tasks)} tasks | tick={tick_interval}s"
        )

        task_dict = {t.name: t for t in self._tasks}
        
        if self._watchdog_timeout:
            import threading
            self._last_tick_time = time.time()
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()

        session_ticks = 0
        while self._running:
            self._last_tick_time = time.time()
            # max_ticks chi dem theo session hien tai (khong tich luy giua cac lan goi run())
            if max_ticks is not None and session_ticks >= max_ticks:
                self._running = False
                break

            self._tick_count += 1
            session_ticks += 1
            now = time.time()

            # Rebuild task_dict neu co thay doi (register/unregister)
            if not self._sorted:
                self._sort_tasks()
                task_dict = {t.name: t for t in self._tasks}

            for task in list(self._tasks):
                if task.state != "RUNNING":
                    continue

                if (now - task.last_run) < task.interval:
                    continue

                #                 # Neu bat ky dependency nao bi PAUSED/STOPPED -> skip task nay
                dep_blocked = False
                for dep_name in task.depends_on:
                    dep = task_dict.get(dep_name)
                    if dep is not None and dep.state != "RUNNING":
                        logger.debug(
                            f"  [SKIP] Task '{task.name}' bi block vi "
                            f"dependency '{dep_name}' dang {dep.state}"
                        )
                        dep_blocked = True
                        break
                if dep_blocked:
                    if hasattr(task.callback, "__self__"):
                        task_inst = task.callback.__self__
                        if hasattr(task_inst, "handle_dependency_failure"):
                            try:
                                task_inst.handle_dependency_failure()
                            except Exception as e:
                                logger.error(f"[LOI] Fallback cua '{task.name}' that bai: {e}")
                    
                    logger.warning(
                        f"  [SKIP] Task '{task.name}' bo qua vong lap nay do dependency '{dep_name}' loi."
                    )
                    continue

                start = time.time()
                try:
                    if task.generator is not None:
                        try:
                            next(task.generator)
                        except StopIteration:
                            task.generator = None
                            task.last_run  = now
                            task.run_count += 1
                    else:
                        task.last_run = now
                        res = task.callback()
                        if hasattr(res, "__iter__") and hasattr(res, "__next__"):
                            task.generator = res
                            try:
                                next(task.generator)
                            except StopIteration:
                                task.generator = None
                                task.run_count += 1
                        else:
                            task.run_count += 1

                    elapsed = time.time() - start
                    task.consecutive_errors = 0
                    task.total_exec_time += elapsed
                    if elapsed > task.max_exec_time:
                        task.max_exec_time = elapsed

                    if self._watchdog_timeout and elapsed > self._watchdog_timeout:
                        logger.warning(
                            f"[WATCHDOG] Task '{task.name}' chay {elapsed:.1f}s "
                            f"> timeout {self._watchdog_timeout}s"
                        )

                except Exception as e:
                    task.generator = None
                    task.error_count += 1
                    task.consecutive_errors += 1
                    task.last_error = str(e)

                    logger.error(f"[LOI] Task '{task.name}': {e}")

                    if self._on_error_callback:
                        try:
                            self._on_error_callback(task.name, e)
                        except Exception:
                            pass

                    if task.consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        task.state = "PAUSED"
                        logger.error(
                            f"[DISABLED] Task '{task.name}' bi PAUSED "
                            f"sau {task.consecutive_errors} loi lien tiep"
                        )

            # Event-driven sleep
            now_end = time.time()
            next_run = min(
                (t.last_run + t.interval for t in self._tasks if t.state == "RUNNING"),
                default=now_end + tick_interval,
            )
            wait_time = max(0.001, min(next_run - now_end, tick_interval))
            time.sleep(wait_time)

    def stop(self) -> None:
        """Dung scheduler."""
        self._running = False
        for task in self._tasks:
            task.state = "STOPPED"
        logger.info("Scheduler dang dung...")

    def get_diagnostics(self) -> List[dict]:
        return [
            {
                "name":       t.name,
                "state":      t.state,
                "runs":       t.run_count,
                "errors":     t.error_count,
                "avg_ms":     round(t.avg_exec_time_ms(), 2),
                "max_ms":     round(t.max_exec_time * 1000, 2),
                "last_error": t.last_error,
                "deps":       t.depends_on,
            }
            for t in self._tasks
        ]

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def task_count(self) -> int:
        return len(self._tasks)
