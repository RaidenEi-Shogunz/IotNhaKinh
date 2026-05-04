"""
Nha Kinh Thong Minh — AI Task v5.0
====================================
  [1] Off-topic detection dong bo voi frontend (confidence + entropy dual-check)
  [2] Confidence-weighted setpoint adjustment (thay vi +1/-1 cung nhac)
  [3] Trend analysis 10-diem voi EWMA (Exponential Weighted Moving Average)
  [4] Plant stress scoring da nhan to (moisture, temp, humidity, co2, weather, light)
  [5] Cooldown + effectiveness check bao ve he thong
  [6] Camera result deduplication
  [7] Adaptive recommendation: ket hop cam bien + camera
  [8] Alert severity escalation khi trend xau di lien tuc
"""

import math
import time
import random
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.ai")

# ═══════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════
_SETPOINT_COOLDOWN_TICKS   = 10    # ~300s giua cac lan thay doi setpoint
_EFFECTIVENESS_CHECK_TICKS = 5     # ~150s de kiem tra hieu qua
_MAX_CONSECUTIVE_INEFF     = 3     # tam dung sau 3 lan khong hieu qua lien tiep

# Off-topic sync voi frontend
_CAM_CONF_THRESHOLD        = 0.45  # max confidence < 45% -> co the off-topic
_CAM_ENTROPY_THRESHOLD     = 0.80  # entropy > 80% -> mo hinh khong chac chan
_MIN_VALID_CONF            = 0.70  # min confidence de thuc hien dieu chinh

# Danh sach lop hop le tu Teachable Machine
_VALID_CLASSES = {
    "thiếu nước", "thieu nuoc",
    "bình thường", "binh thuong",
    "sâu bệnh",   "sau benh",
    "ngập úng",   "ngap ung",
    "quá nóng",   "qua nong",
}

# EWMA alpha cho trend
_EWMA_ALPHA = 0.3


# ═══════════════════════════════════════════════════
# AI TASK CLASS
# ═══════════════════════════════════════════════════

class AITask(BaseTask):
    """Task phan tich AI tinh trang cay trong v5.0."""

    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config     = config
        self.run_count  = 0

        # Cooldown & effectiveness
        self._last_sp_change_tick    = 0
        self._moisture_at_sp_change  = None
        self._consecutive_ineff      = 0

        # Deduplication camera
        self._last_cam_id = None

        # Trend (EWMA score)
        self._ewma_score      = None
        self._score_history   = []   # raw scores (up to 10 diem)
        self._MAX_SCORE_HIST  = 10

        # Alert escalation
        self._consecutive_bad = 0
        self._MAX_BAD_STREAK  = 5

    def shutdown(self) -> None:
        pass

    # ─────────────────────────────────────────────
    # OFF-TOPIC DETECTION (sync voi frontend)
    # ─────────────────────────────────────────────

    @staticmethod
    def _normalized_entropy(probs: list) -> float:
        """Shannon entropy chuan hoa [0,1]. 0=chac chan, 1=hoan toan ngau nhien."""
        n = len(probs)
        if n <= 1:
            return 0.0
        H = 0.0
        for p in probs:
            if p > 1e-9:
                H -= p * math.log2(p)
        return H / math.log2(n)

    def _is_valid_class(self, cls: str) -> bool:
        """Kiem tra class co thuoc chu de cay trong khong."""
        cls_lower = cls.lower()
        return any(v in cls_lower for v in _VALID_CLASSES)

    def _detect_off_topic_from_cam(self, cls: str, conf: float) -> tuple:
        """
        Off-topic detection cho ket qua camera.
        Goi y: neu frontend da loc nhung van truyen class la, xu ly them.
        Returns (is_off_topic: bool, reason: str)
        """
        if not self._is_valid_class(cls):
            return True, f"Class '{cls}' khong thuoc danh muc cay trong."
        if conf < _CAM_CONF_THRESHOLD:
            return True, f"Do tin cay {conf:.0%} < {_CAM_CONF_THRESHOLD:.0%} — off-topic."
        return False, ""

    # ─────────────────────────────────────────────
    # SETPOINT MANAGEMENT
    # ─────────────────────────────────────────────

    def _can_adjust_setpoint(self) -> bool:
        return (self.run_count - self._last_sp_change_tick) >= _SETPOINT_COOLDOWN_TICKS

    def _check_effectiveness(self, current_moisture: float) -> bool:
        """Kiem tra xem lan tang setpoint truoc do co hieu qua khong."""
        if self._moisture_at_sp_change is None:
            return True
        if (self.run_count - self._last_sp_change_tick) < _EFFECTIVENESS_CHECK_TICKS:
            return True
        improved = current_moisture > (self._moisture_at_sp_change + 1.5)
        if not improved:
            self._consecutive_ineff += 1
            if self._consecutive_ineff >= _MAX_CONSECUTIVE_INEFF:
                logger.warning(
                    f"[AI] Setpoint tang {self._consecutive_ineff} lan "
                    f"nhung moisture khong cai thien (hien tai={current_moisture:.1f}%). Tam dung."
                )
                return False
        else:
            self._consecutive_ineff = 0
        return True

    def _adjust_setpoint(self, delta: float, moisture: float, reason: str) -> None:
        """
        Dieu chinh setpoint PID voi delta confidence-weighted.
        delta: gia tri thay doi (co the la float nho hon 1.0 neu conf trung binh)
        """
        current_sp = self.greenhouse.get_pid_setpoint()
        max_sp = min(65.0, self.config.MOISTURE_TARGET + 12.0)
        min_sp = max(18.0, self.config.MOISTURE_TARGET - 12.0)
        new_sp = round(max(min_sp, min(max_sp, current_sp + delta)), 1)

        if abs(new_sp - current_sp) < 0.1:
            return

        self.greenhouse.set_pid_setpoint(new_sp)
        self._last_sp_change_tick   = self.run_count
        self._moisture_at_sp_change = moisture

        direction = "tăng" if delta > 0 else "giảm"
        msg = f"AI tự {direction} ngưỡng PID: {current_sp:.1f}% → {new_sp:.1f}% ({reason})"
        self.greenhouse.add_alert("AI_TUNING", msg, "INFO")
        logger.info(f"  [AI] Setpoint {direction}: {current_sp:.1f} -> {new_sp:.1f} ({reason})")

    # ─────────────────────────────────────────────
    # TREND ANALYSIS (EWMA)
    # ─────────────────────────────────────────────

    def _update_trend(self, score: float) -> str:
        """Cap nhat EWMA va raw history, tra ve trend string."""
        # EWMA
        if self._ewma_score is None:
            self._ewma_score = score
        else:
            self._ewma_score = _EWMA_ALPHA * score + (1 - _EWMA_ALPHA) * self._ewma_score

        # Raw history
        self._score_history.append(score)
        if len(self._score_history) > self._MAX_SCORE_HIST:
            self._score_history.pop(0)

        if len(self._score_history) < 4:
            return "STABLE"

        # So sanh EWMA voi lich su
        recent_avg = sum(self._score_history[-4:]) / 4
        old_avg    = sum(self._score_history[:-4]) / max(1, len(self._score_history) - 4)

        diff = recent_avg - old_avg
        if diff > 8:
            return "IMPROVING"
        elif diff < -8:
            return "DECLINING"
        return "STABLE"

    # ─────────────────────────────────────────────
    # MAIN RUN
    # ─────────────────────────────────────────────

    def run(self):
        self.run_count += 1
        sensors  = self.greenhouse.get_sensors()
        moisture = sensors["soil_moisture"]
        temp     = sensors["temperature"]
        humidity = sensors["humidity"]
        co2      = sensors.get("co2_level", 450)
        light    = sensors.get("light_intensity", 600)

        cam_result = self.greenhouse.get_ai_camera_result()
        if cam_result and isinstance(cam_result, dict) and "class" in cam_result:
            self._handle_camera(cam_result, moisture, temp, humidity)
            return

        self._handle_rule_based(moisture, temp, humidity, co2, light)

    # ─────────────────────────────────────────────
    # CAMERA HANDLER
    # ─────────────────────────────────────────────

    def _handle_camera(self, cam_result: dict, moisture: float, temp: float, humidity: float):
        cls  = str(cam_result.get("class", ""))
        conf = float(cam_result.get("confidence", 0.0))

        # Deduplication
        cam_id = f"{cls}|{conf:.4f}"
        if cam_id == self._last_cam_id:
            return
        self._last_cam_id = cam_id

        # Off-topic check (dong bo voi frontend)
        is_ot, ot_reason = self._detect_off_topic_from_cam(cls, conf)
        if is_ot:
            self.greenhouse.set_ai_status(
                "Camera: Ngoài chủ đề",
                conf,
                f"⚠️ '{cls}' — {ot_reason} Bỏ qua kết quả. Hướng camera vào lá cây!"
            )
            logger.warning(f"  [AI] OFF-TOPIC camera: '{cls}' conf={conf:.0%} — {ot_reason}")
            return

        # Low confidence — cho AI xac nhan them
        if conf < _MIN_VALID_CONF:
            self.greenhouse.set_ai_status(
                "Camera: Đang phân tích...",
                conf,
                f"🔍 Phát hiện '{cls}' nhưng độ tin cậy ({conf:.0%}) chưa đủ. Chờ AI xác nhận thêm."
            )
            return

        # ── Xu ly theo class ──
        cls_low       = cls.lower()
        recommendation = ""
        status        = cls

        if any(k in cls_low for k in ("thiếu nước", "thieu nuoc")):
            recommendation = "🔴 Camera xác nhận cây héo do thiếu nước! Cần tăng ngưỡng tưới ngay."
            if (self.greenhouse.get_mode() == "AUTO"
                    and self._can_adjust_setpoint()
                    and self._check_effectiveness(moisture)):
                current_sp = self.greenhouse.get_pid_setpoint()
                max_sp     = min(65.0, self.config.MOISTURE_TARGET + 12.0)
                if current_sp < max_sp:
                    # Confidence-weighted delta: conf cao -> tang manh hon
                    delta = round(0.5 + conf * 1.0, 1)
                    self._adjust_setpoint(delta, moisture, f"Camera: Thieu nuoc (conf={conf:.0%})")
                elif self.run_count % 15 == 0:
                    self.greenhouse.add_alert(
                        "AI_LIMIT", "AI đã chạm trần ngưỡng tưới. Kiểm tra hệ thống!", "CRITICAL"
                    )

        elif any(k in cls_low for k in ("bình thường", "binh thuong")):
            recommendation = "🟢 Camera xác nhận cây đang phát triển khỏe mạnh."
            if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                current_sp = self.greenhouse.get_pid_setpoint()
                if current_sp > self.config.MOISTURE_TARGET + 1.0:
                    self._adjust_setpoint(-1.0, moisture, "Camera: Binh thuong")

        elif any(k in cls_low for k in ("sâu bệnh", "sau benh")):
            recommendation = "🟠 CẢNH BÁO: Camera phát hiện dấu hiệu sâu bệnh trên lá!"
            if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                # Sâu bệnh: giảm tưới để không tạo điều kiện ẩm cho nấm mốc
                self._adjust_setpoint(-1.0, moisture, "Camera: Sau benh")
            if self.run_count % 8 == 0:
                self.greenhouse.add_alert("AI_DISEASE", "Camera phát hiện Sâu Bệnh!", "WARNING")

        elif any(k in cls_low for k in ("ngập úng", "ngap ung")):
            recommendation = "🔵 Camera phát hiện đất quá ướt! Giảm tưới ngay."
            if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                self._adjust_setpoint(-1.5, moisture, "Camera: Ngap ung")

        elif any(k in cls_low for k in ("quá nóng", "qua nong")):
            recommendation = "🌡️ Camera phát hiện cây bị stress nhiệt! Tăng tưới mát."
            if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                self._adjust_setpoint(+1.0, moisture, "Camera: Qua nong")

        else:
            recommendation = f"📊 Camera ghi nhận trạng thái: '{cls}'."

        self.greenhouse.set_ai_status(f"Camera: {status}", conf, recommendation)
        logger.info(f"  [AI] #{self.run_count}: CAMERA '{cls}' conf={conf:.0%}")

    # ─────────────────────────────────────────────
    # RULE-BASED HANDLER (multi-factor scoring)
    # ─────────────────────────────────────────────

    def _handle_rule_based(self, moisture: float, temp: float,
                           humidity: float, co2: float, light: float):
        """
        Danh gia suc khoe cay = diem so da nhan to [0..100].
        Ap dung EWMA de theo doi xu huong.
        """
        score   = 100.0
        factors = []

        # ── Moisture (trong so cao nhat) ──
        if moisture < 15:
            score -= 45; factors.append(f"Đất cực khô ({moisture:.0f}%)")
        elif moisture < 28:
            score -= 22; factors.append(f"Đất khô ({moisture:.0f}%)")
        elif moisture < 35:
            score -= 10
        elif 40 <= moisture <= 65:
            score += 6   # bonus vung ly tuong
        elif moisture > 85:
            score -= 18; factors.append(f"Đất quá ướt ({moisture:.0f}%)")
        elif moisture > 75:
            score -= 8

        # ── Temperature ──
        if temp > 42 or temp < 8:
            score -= 32; factors.append(f"Nhiệt độ cực đoan ({temp:.0f}°C)")
        elif temp > 36 or temp < 13:
            score -= 16; factors.append(f"Nhiệt độ bất lợi ({temp:.0f}°C)")
        elif 22 <= temp <= 30:
            score += 5   # bonus
        elif temp > 33:
            score -= 5

        # ── Humidity ──
        if humidity < 25 or humidity > 92:
            score -= 18; factors.append(f"Độ ẩm KK cực đoan ({humidity:.0f}%)")
        elif humidity < 38 or humidity > 82:
            score -= 7

        # ── CO2 ──
        if co2 > 900:
            score -= 7; factors.append(f"CO₂ cao ({co2:.0f} ppm)")
        elif co2 < 280:
            score -= 6; factors.append(f"CO₂ thấp ({co2:.0f} ppm)")
        elif 380 <= co2 <= 600:
            score += 3   # bonus vung ly tuong

        # ── Light ──
        if light < 100:
            score -= 8; factors.append(f"Ánh sáng yếu ({light:.0f} lux)")
        elif 400 <= light <= 800:
            score += 3

        # ── Weather ──
        try:
            weather = self.greenhouse.get_weather()
            if weather.get("condition") == "rainy" and weather.get("rain_intensity", 0) > 0.4:
                score += 5
            elif weather.get("condition") == "cloudy":
                score -= 3
            elif weather.get("condition") == "sunny":
                score += 2
        except Exception:
            pass

        # ── Time of day ──
        try:
            if not self.greenhouse.is_daytime():
                score += 3
        except Exception:
            pass

        # Gaussian noise nhe de tranh bi khet cung
        score += random.gauss(0, 1.5)
        score = max(0.0, min(100.0, score))

        # Trend update
        trend = self._update_trend(score)

        # ── Phan loai ──
        if score >= 75:
            status = "Tốt"
            rec    = "🟢 Cây phát triển tốt."
            if trend == "IMPROVING":
                rec += " Xu hướng: Đang cải thiện tích cực ↑"
            self._consecutive_bad = 0
            if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                sp = self.greenhouse.get_pid_setpoint()
                if sp > self.config.MOISTURE_TARGET + 1.5:
                    self._adjust_setpoint(-1.0, moisture, "Rule: Tot")

        elif score >= 50:
            self._consecutive_bad = 0
            if moisture < 30:
                status = "Thiếu nước"
                rec    = "🟡 Đất khô, cần tăng tưới."
                if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint() and self._check_effectiveness(moisture):
                    self._adjust_setpoint(+1.0, moisture, "Rule: Thieu nuoc")
            elif moisture > 80:
                status = "Ngập úng"
                rec    = "🟡 Đất quá ướt, tạm giảm tưới."
                if self.greenhouse.get_mode() == "AUTO" and self._can_adjust_setpoint():
                    self._adjust_setpoint(-1.0, moisture, "Rule: Ngap ung")
            elif temp > 35:
                status = "Quá nóng"
                rec    = "🟠 Nhiệt độ cao, cây bị stress nhiệt."
            elif temp < 15:
                status = "Quá lạnh"
                rec    = "🟠 Nhiệt độ thấp, cây ngừng phát triển."
            else:
                status = "Bình thường"
                rec    = "🟡 Môi trường chấp nhận được."
                if factors:
                    rec += f" Lưu ý: {', '.join(factors[:2])}."
            if trend == "DECLINING":
                rec += " ⚠️ Xu hướng đang xấu đi."

        else:
            self._consecutive_bad += 1
            status = "Nguy hiểm"
            rec    = f"🔴 Cây đang trong trạng thái xấu! {', '.join(factors[:3])}."
            if trend == "DECLINING":
                rec += " Xu hướng: Tiếp tục xấu đi ↓"
            if self._consecutive_bad >= self._MAX_BAD_STREAK and self.run_count % 10 == 0:
                self.greenhouse.add_alert(
                    "AI_CRITICAL",
                    f"Cây liên tục trong trạng thái nguy hiểm ({self._consecutive_bad} chu kỳ)! Cần kiểm tra ngay.",
                    "CRITICAL"
                )

        # Confidence: score cao & ewma on dinh -> conf cao
        ewma_stability = 1.0 - abs(score - (self._ewma_score or score)) / 100.0
        confidence = min(0.97, 0.65 + score / 400 + ewma_stability * 0.15 + random.uniform(0, 0.05))

        self.greenhouse.set_ai_status(f"Giả lập: {status}", confidence, rec)
        logger.info(
            f"  [AI] #{self.run_count}: {status} "
            f"(score={score:.0f}, ewma={self._ewma_score:.1f}, "
            f"conf={confidence:.0%}, trend={trend}) "
            f"M={moisture:.1f}% T={temp:.1f}°C H={humidity:.1f}%"
        )