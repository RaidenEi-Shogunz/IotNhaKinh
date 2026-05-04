"""
Nha Kinh Thong Minh - Machine Learning Predictive Task
======================================================
Du doan do am tuong lai de canh bao / bat bom chu dong.
"""

import time
import sqlite3
import logging
from typing import Any, List, Dict
from tasks.base_task import BaseTask

logger = logging.getLogger("task.predict")

class PredictiveTask(BaseTask):
    def __init__(self, greenhouse: Any, config: Any, db_path: str = "dulieu_nhakinh.db"):
        self.greenhouse = greenhouse
        self.config = config
        self.db_path = db_path
        
        # Inject truong du lieu vao greenhouse
        if not hasattr(self.greenhouse, "prediction_points"):
            self.greenhouse.prediction_points = []
            
    def run(self) -> None:
        """Thuc thi ML bang Linear Regression (Cong thuc Toan hoc)"""
        try:
            # Query 60 diem du lieu gan nhat
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, soil_moisture FROM sensor_data ORDER BY timestamp DESC LIMIT 60"
            ).fetchall()
            conn.close()
            
            if len(rows) < 15:
                return # Chua du data de hoc

            # Dao nguoc rows thanh thu tu thoi gian tang dan
            rows.reverse()

            n = len(rows)
            sum_x = sum_Y = sum_xY = sum_xx = 0.0
            
            # Lay t0 la diem bat dau
            t0 = rows[0]["timestamp"]
            
            import math
            for r in rows:
                # Chuyen ve thang phut mo phong (vi 1 giay thuc = config.TIME_SCALE phut mo phong)
                x = ((r["timestamp"] - t0) * self.config.TIME_SCALE) / 60.0
                y = r["soil_moisture"]
                if y <= 0: y = 0.1 # Tranh log(0)
                Y = math.log(y)
                sum_x += x
                sum_Y += Y
                sum_xx += x*x
                sum_xY += x*Y
                
            # Log-Linear Regression (Exponential Decay): Y = m*x + b' => y = e^(m*x + b')
            denominator = (n * sum_xx - sum_x * sum_x)
            if denominator == 0:
                return
            
            m = (n * sum_xY - sum_x * sum_Y) / denominator
            b_prime = (sum_Y - m * sum_x) / n
            
            current_moisture = self.greenhouse.get_sensors()["soil_moisture"]
            
            # Neu m >= 0 (dat dang uot len do tuoi hoac giu nguyen), khong the du doan can
            if m >= -0.0001:
                self.greenhouse.prediction_points = []
                return
                
            # Tinh thoi gian (phut mo phong) con lai de cham nguong canh bao
            threshold = self.greenhouse.get_threshold()
            current_x = ((time.time() - t0) * self.config.TIME_SCALE) / 60.0
            
            # y = e^(mx + b') => ln(y) = mx + b' => x_target = (ln(threshold) - b') / m
            if threshold <= 0: threshold = 0.1
            x_target = (math.log(threshold) - b_prime) / m
            sim_minutes_left = x_target - current_x
            
            predictions = []
            now_ts = time.time()
            
            # Ve duong cong du doan gom 4 diem trong tuong lai
            if sim_minutes_left > 0:
                step = sim_minutes_left / 4.0
                for i in range(1, 5):
                    fut_sim_min = i * step
                    # fut_val = e^(m * (current_x + fut_sim_min) + b_prime)
                    fut_x = current_x + fut_sim_min
                    fut_val = math.exp(m * fut_x + b_prime)
                    
                    if fut_val < threshold:
                        fut_val = threshold
                        
                    # Chuyen phut mo phong nguoc lai thanh giay thuc te de ve tren Chart.js
                    real_seconds_future = (fut_sim_min * 60.0) / self.config.TIME_SCALE
                    fut_ts = now_ts + real_seconds_future
                    
                    predictions.append({
                        "timestamp": fut_ts,
                        "value": round(fut_val, 1)
                    })
                    
                self.greenhouse.prediction_points = predictions
                
                # PREDICTIVE WATERING: Neu chi con duoi 15 phut mo phong la dat kho han
                # Va che do la AUTO, bom chua chay -> Bat bom som truoc khi cay heo!
                if sim_minutes_left < 15.0 and self.greenhouse.get_mode() == "AUTO" and not self.greenhouse.is_pump_on():
                    logger.warning(f"🔮 [AI PREDICT] Dat se kho nứt trong {sim_minutes_left:.1f} phut mo phong toi (Toc do: {m:.2f}%/phut).")
                    logger.warning(f"🔮 [AI PREDICT] Kich hoat PREDICTIVE WATERING (Tuoi nuoc chu dong)!")
                    self.greenhouse.set_pump(True, trigger="AI_PREDICT")
                    self.greenhouse.add_alert("AI_PREDICT", f"Tuoi chu dong. Du doan kho sau {sim_minutes_left:.1f} phut", "WARNING")

        except Exception as e:
            logger.error(f"[PREDICT] Loi: {e}")

    def shutdown(self) -> None:
        """Don dep resources khi thoat"""
        pass
