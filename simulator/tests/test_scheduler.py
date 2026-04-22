"""
Test Cooperative Scheduler - NANG CAP v3.0
Kiem tra:
  [1] Topological sort + Priority
  [2] Dependency enforcement that su (PAUSED dep -> skip task)
  [3] Dynamic priority change
  [4] Task lifecycle (RUNNING/PAUSED/STOPPED)
  [5] Generator preemption (yield)
  [6] Auto-pause sau 5 loi lien tiep
  [7] _sorted flag (khong rebuild thu tu neu khong can)
"""
import sys
import os
import time
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.scheduler import CooperativeScheduler


class TestCooperativeScheduler(unittest.TestCase):

    def setUp(self):
        self.scheduler       = CooperativeScheduler(watchdog_timeout=0.1)
        self.execution_order = []

    # ------------------------------------------------------------------
    def test_priority_and_dependency_execution(self):
        """C phu thuoc B, B phu thuoc A -> thu tu: A, B, C."""
        def task_a(): self.execution_order.append("A")
        def task_b(): self.execution_order.append("B")
        def task_c(): self.execution_order.append("C")

        self.scheduler.register_task("C", task_c, interval=0.1, priority=10, depends_on=["B"])
        self.scheduler.register_task("A", task_a, interval=0.1, priority=1)
        self.scheduler.register_task("B", task_b, interval=0.1, priority=5, depends_on=["A"])

        self.scheduler.run(tick_interval=0.01, max_ticks=1)
        self.assertEqual(self.execution_order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    def test_dependency_enforcement_paused(self):
        """
        NANG CAP: Neu dependency bi PAUSED, task phu thuoc phai bi skip.
        Day la test dependency enforcement that su (khong chi thu tu).
        """
        ran_b = []

        def task_a(): pass     # A bi pause ngay sau khi register
        def task_b(): ran_b.append(True)

        self.scheduler.register_task("A", task_a, interval=0.0, priority=5)
        self.scheduler.register_task("B", task_b, interval=0.0, priority=3, depends_on=["A"])

        # Pause task A truoc khi chay
        self.scheduler.pause_task("A")

        # Chay 1 tick
        self.scheduler.run(tick_interval=0.01, max_ticks=1)

        self.assertEqual(len(ran_b), 0,
                         "B khong duoc chay khi dependency A dang PAUSED")

    # ------------------------------------------------------------------
    def test_dependency_enforcement_resumes(self):
        """Sau khi resume A, B phai chay binh thuong lai."""
        ran_b = []

        def task_a(): pass
        def task_b(): ran_b.append(True)

        self.scheduler.register_task("A", task_a, interval=0.0, priority=5)
        self.scheduler.register_task("B", task_b, interval=0.0, priority=3, depends_on=["A"])

        # Pause roi resume A
        self.scheduler.pause_task("A")
        self.scheduler.resume_task("A")

        self.scheduler.run(tick_interval=0.01, max_ticks=1)
        self.assertGreater(len(ran_b), 0, "B phai chay khi A da duoc resume")

    # ------------------------------------------------------------------
    def test_dynamic_priority_change(self):
        """Thay doi priority tai runtime phai sap xep lai."""
        self.scheduler.register_task("A", lambda: None, interval=1.0, priority=5)
        self.scheduler.register_task("B", lambda: None, interval=1.0, priority=10)

        self.assertEqual(self.scheduler._tasks[0].name, "B")

        self.scheduler.set_priority("A", 20)
        self.assertEqual(self.scheduler._tasks[0].name, "A")

    # ------------------------------------------------------------------
    def test_task_lifecycle(self):
        """RUNNING -> PAUSED -> RUNNING -> STOPPED."""
        self.scheduler.register_task("LifecycleTask", lambda: None, interval=1.0, priority=5)
        task = self.scheduler._tasks[0]
        self.assertEqual(task.state, "RUNNING")

        self.scheduler.pause_task("LifecycleTask")
        self.assertEqual(task.state, "PAUSED")

        self.scheduler.resume_task("LifecycleTask")
        self.assertEqual(task.state, "RUNNING")

        self.scheduler.unregister_task("LifecycleTask")
        self.assertEqual(len(self.scheduler._tasks), 0)

    # ------------------------------------------------------------------
    def test_generator_preemption(self):
        """
        Task dung yield phai thuc thi tung buoc qua cac tick.

        LUU Y ve max_ticks: moi lan goi run(max_ticks=N) dem N tick MOI
        (khong tich luy giua cac lan goi).
        Moi tick chi thuc thi BUOC HIEN TAI cua generator.
        """
        self.steps = []

        def chunked_task():
            self.steps.append(1)
            yield
            self.steps.append(2)
            yield
            self.steps.append(3)

        self.scheduler.register_task("Chunked", chunked_task, interval=0.0, priority=5)

        # Tick 1: tao generator va chay den yield dau tien
        self.scheduler.run(tick_interval=0.001, max_ticks=1)
        self.assertEqual(self.steps, [1], "Tick 1: chi thuc hien buoc 1")

        # Tick 2: tiep tuc generator den yield thu hai
        self.scheduler.run(tick_interval=0.001, max_ticks=1)
        self.assertEqual(self.steps, [1, 2], "Tick 2: thuc hien buoc 2")

        # Tick 3: tiep tuc den het (StopIteration)
        self.scheduler.run(tick_interval=0.001, max_ticks=1)
        self.assertEqual(self.steps, [1, 2, 3], "Tick 3: thuc hien buoc 3 va ket thuc generator")

    # ------------------------------------------------------------------
    def test_auto_pause_after_consecutive_errors(self):
        """Task bi PAUSED tu dong sau 5 loi lien tiep."""
        def broken_task():
            raise ValueError("Loi co y")

        self.scheduler.register_task("Broken", broken_task, interval=0.0, priority=5)
        task = self.scheduler._tasks[0]

        # Chay du 5 lan de kích hoat auto-pause
        self.scheduler.run(tick_interval=0.001, max_ticks=5)

        self.assertEqual(task.state, "PAUSED",
                         "Task phai bi PAUSED sau 5 loi lien tiep")
        self.assertEqual(task.consecutive_errors, 5)

    # ------------------------------------------------------------------
    def test_sorted_flag_optimization(self):
        """_sorted flag phai False sau register, True sau sort."""
        s = CooperativeScheduler()
        self.assertTrue(s._sorted)  # Ban dau True (khong co task)

        s.register_task("X", lambda: None, interval=1.0)
        # Sau register, _sort_tasks duoc goi -> _sorted = True
        self.assertTrue(s._sorted)

        # Sau set_priority, _sorted = False roi sort lai -> True
        s.set_priority("X", 99)
        self.assertTrue(s._sorted)

    # ------------------------------------------------------------------
    def test_circular_dependency_detection(self):
        """Scheduler phai xu ly circular dependency ma khong crash."""
        def t(): pass
        # A -> B -> A (circular)
        self.scheduler.register_task("A", t, interval=1.0, depends_on=["B"])
        self.scheduler.register_task("B", t, interval=1.0, depends_on=["A"])
        # Khong crash -> pass
        self.scheduler.run(tick_interval=0.001, max_ticks=1)


if __name__ == '__main__':
    unittest.main()
