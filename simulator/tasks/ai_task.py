"""
Nha Kinh Thong Minh - Task Phan Tich AI
=========================================
Mo phong phan tich tinh trang cay trong dua tren
nhieu cam bien. Phase 4 se tich hop Teachable Machine.
"""

import random
import logging

logger = logging.getLogger("task.ai")


class AITask:
    """Task phan tich AI tinh trang cay trong."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self.run_count = 0

    def run(self):
        self.run_count += 1
        sensors = self.greenhouse.get_sensors()
        moisture = sensors["soil_moisture"]
        temp = sensors["temperature"]
        humidity = sensors["humidity"]

        # Tinh diem suc khoe (0-100)
        score = 100

        # Do am dat
        if moisture < 20:
            score -= 40
        elif moisture < 30:
            score -= 20
        elif moisture > 80:
            score -= 15

        # Nhiet do
        if temp > 40 or temp < 10:
            score -= 30
        elif temp > 35 or temp < 15:
            score -= 15

        # Do am khong khi
        if humidity < 30 or humidity > 90:
            score -= 15
        elif humidity < 40 or humidity > 80:
            score -= 5

        # Nhieu nho
        score += random.gauss(0, 3)
        score = max(0, min(100, score))

        # Phan loai
        if score >= 70:
            status = "Binh thuong"
            recommendation = "Cay phat trien tot, khong can dieu chinh."
        elif score >= 40:
            status = "Thieu nuoc"
            recommendation = "Can tang tan suat tuoi hoac tang nguong do am."
            # Tu dong tang setpoint
            current_sp = self.greenhouse.get_pid_setpoint()
            if current_sp < 60:
                self.greenhouse.set_pid_setpoint(current_sp + 2)
        else:
            status = "Nguy hiem"
            recommendation = "Cay trong trang thai xau! Kiem tra ngay!"

        confidence = min(0.99, 0.7 + score / 500 + random.uniform(0, 0.1))

        self.greenhouse.set_ai_status(status, confidence, recommendation)

        logger.info(
            f"  [AI] #{self.run_count}: {status} "
            f"(diem={score:.0f}, do tin cay={confidence:.0%}) | "
            f"M={moisture:.1f}%"
        )
