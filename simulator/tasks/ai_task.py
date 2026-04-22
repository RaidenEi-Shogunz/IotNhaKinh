"""
Nha Kinh Thong Minh - Task Phan Tich AI
=========================================
Mo phong phan tich tinh trang cay trong dua tren
nhieu cam bien. Phase 4 se tich hop Teachable Machine.
"""

import random
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.ai")


class AITask(BaseTask):
    """Task phan tich AI tinh trang cay trong."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self.run_count = 0

    def shutdown(self) -> None:
        """Khong co tai nguyen can giai phong."""
        pass

    def run(self):
        self.run_count += 1
        sensors = self.greenhouse.get_sensors()
        moisture = sensors["soil_moisture"]
        temp = sensors["temperature"]
        humidity = sensors["humidity"]

        # 1. Kiem tra xem co du lieu tu Camera AI (Teachable Machine) khong
        cam_result = self.greenhouse.get_ai_camera_result()
        if cam_result and "class" in cam_result:
            cls = cam_result["class"]
            conf = float(cam_result.get("confidence", 0.0))
            # FIX Thieu: Validation confidence toi thieu (Tin cay phai >= 70%)
            if conf < 0.70:
                recommendation = f"Phát hiện '{cls}' nhưng độ tin cậy thấp ({conf:.0%}). Chờ AI xác nhận thêm."
                self.greenhouse.set_ai_status(f"Camera: Đang phân tích...", conf, recommendation)
                self.greenhouse.set_ai_camera_result(None)
                return

            status = cls
            
            if "Thieu nuoc" in cls or "Thiếu nước" in cls:
                recommendation = "Camera phát hiện cây héo do thiếu nước. Cần tăng ngưỡng tưới."
                current_sp = self.greenhouse.get_pid_setpoint()
                
                # FIX Bug An 10 (Design): Hard-ceiling cho Setpoint de chong chay nguong (Runaway setpoint)
                # Max = Target ban dau + 10%. (Vi du Target=30 -> Max=40)
                max_sp = min(60.0, self.config.MOISTURE_TARGET + 10.0)
                
                if current_sp < max_sp:
                    # Giam toc do tang (+1 thay vi +2, delay lau hon)
                    if self.run_count % 5 == 0 and self.greenhouse.get_mode() == "AUTO":
                        self.greenhouse.set_pid_setpoint(current_sp + 1.0)
                        self.greenhouse.add_alert("AI_TUNING", f"AI tự tăng ngưỡng PID lên {current_sp+1.0}% do thiếu nước", "INFO")
                elif self.run_count % 15 == 0:
                    # Neu dung tran nhung camera van bao Thieu Nuoc, phai canh bao User!
                    self.greenhouse.add_alert("AI_LIMIT_REACHED", "AI không thể tăng ngưỡng tưới thêm (đã chạm trần). Hãy kiểm tra hệ thống nước thực tế!", "CRITICAL")
                    
            elif "Binh thuong" in cls or "Bình thường" in cls:
                recommendation = "Camera xác nhận cây đang phát triển tốt."
                current_sp = self.greenhouse.get_pid_setpoint()
                
                # Chi tu dong dua ve muc Target chuong trinh ban dau (Floor)
                if current_sp > self.config.MOISTURE_TARGET:
                    if self.run_count % 5 == 0 and self.greenhouse.get_mode() == "AUTO":
                        self.greenhouse.set_pid_setpoint(current_sp - 1.0)
                        
            elif "Sau benh" in cls or "Sâu bệnh" in cls:
                recommendation = "CẢNH BÁO: Phát hiện dấu hiệu sâu bệnh trên lá!"
                if self.run_count % 10 == 0:
                    self.greenhouse.add_alert("AI_DISEASE", "Camera phát hiện Sâu Bệnh. Yêu cầu phun thuốc!", "WARNING")
            else:
                recommendation = f"Trạng thái {cls} được ghi nhận từ Camera."

            self.greenhouse.set_ai_status(f"Camera: {status}", conf, recommendation)
            logger.info(f"  [AI] #{self.run_count}: CAMERA DETECTED '{cls}' (tin cậy: {conf:.0%})")
            
            # FIX: Xoa ket qua sau khi da xu ly de tranh loop vo han (nếu camera bị tắt)
            self.greenhouse.set_ai_camera_result(None)
            return

        # 2. Neu KHONG co du lieu tu Camera, su dung thuat toan Base-Rule nhu cu
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
            current_sp = self.greenhouse.get_pid_setpoint()
            if current_sp > self.config.MOISTURE_TARGET and self.run_count % 5 == 0:
                if self.greenhouse.get_mode() == "AUTO":
                    self.greenhouse.set_pid_setpoint(current_sp - 1)
        elif score >= 40:
            if moisture < 30:
                status = "Thieu nuoc"
                recommendation = "Can tang tan suat tuoi hoac tang nguong do am."
                current_sp = self.greenhouse.get_pid_setpoint()
                if current_sp < 60 and self.run_count % 5 == 0:
                    if self.greenhouse.get_mode() == "AUTO":
                        self.greenhouse.set_pid_setpoint(current_sp + 2)
            elif moisture > 80:
                status = "Ngap ung"
                recommendation = "Dat qua uot, can tam ngung tuoi."
                current_sp = self.greenhouse.get_pid_setpoint()
                if current_sp > 30 and self.run_count % 5 == 0:
                    if self.greenhouse.get_mode() == "AUTO":
                        self.greenhouse.set_pid_setpoint(current_sp - 2)
            elif temp > 35:
                status = "Qua nong"
                recommendation = "Nhiet do qua cao, cay bi stress nhiet."
            elif temp < 15:
                status = "Qua lanh"
                recommendation = "Nhiet do qua thap, cay ngung phat trien."
            else:
                status = "Binh thuong (lech nhe)"
                recommendation = "Moi truong khong hoan hao nhung van trong muc chap nhan duoc."
        else:
            status = "Nguy hiem"
            recommendation = "Cay trong trang thai xau! Kiem tra ngay!"

        confidence = min(0.99, 0.7 + score / 500 + random.uniform(0, 0.1))

        self.greenhouse.set_ai_status(f"Giả lập: {status}", confidence, recommendation)

        logger.info(
            f"  [AI] #{self.run_count}: {status} "
            f"(diem={score:.0f}, do tin cay={confidence:.0%}) | "
            f"M={moisture:.1f}%"
        )
