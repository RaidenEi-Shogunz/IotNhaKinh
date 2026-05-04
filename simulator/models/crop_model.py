"""
Nha Kinh Thong Minh - Mo hinh Cay Trong (Crop Model)
=====================================================

Ly thuyet:
  [1] Kc (Crop Coefficient) — FAO Irrigation & Drainage Paper 56:
      ET_crop = Kc × ET_ref
      Kc thay doi theo 4 giai doan sinh truong:
        - Initial    (Kc_ini = 0.3–0.5):  cay con, mat dat thoang
        - Development (Kc tang tuyen tinh): cay phat trien, la phu dan
        - Mid-season  (Kc_mid = 1.0–1.2): cay truong thanh, thoat hoi nuoc max
        - Late-season (Kc_end = 0.4–0.7): cay gia, la rung

  [2] WSI (Water Stress Index) — FAO AquaCrop simplified:
      WSI = 1 - (θ - θ_wp) / (θ_fc - θ_wp)   khi θ < θ_fc
      WSI = 0                                   khi θ ≥ θ_fc
      Voi:
        θ     = do am dat hien tai (%)
        θ_fc  = Field Capacity (suc chua dong ruong)
        θ_wp  = Wilting Point (diem heo)

      WSI = 0: khong stress, cay thoat hoi nuoc toi da
      WSI = 1: cay heo, khong thoat hoi nuoc (stomata dong)

  [3] Ks (Stress coefficient) = 1 - WSI
      ET_actual = Ks × Kc × ET_ref
      CO2_uptake_actual = Ks × CO2_uptake_potential

  [4] Giai doan sinh truong tu dong tien trinh theo sim_day,
      tong so ngay = CROP_TOTAL_DAYS (mac dinh 90 ngay rau).

Tham khao:
  - FAO-56: Allen, R.G. et al., 1998. Crop Evapotranspiration.
  - AquaCrop: Steduto et al., 2009. doi:10.2134/agronj2008.0139s
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any

logger = logging.getLogger("crop_model")


# ============================================================
# Giai doan sinh truong (Growth Stage)
# ============================================================
STAGE_INITIAL     = "initial"       # Giai doan dau (cay con)
STAGE_DEVELOPMENT = "development"   # Phat trien
STAGE_MID_SEASON  = "mid_season"    # Giua mua (truong thanh)
STAGE_LATE_SEASON = "late_season"   # Cuoi mua (thu hoach)


@dataclass
class CropStageInfo:
    """Thong tin mot giai doan sinh truong."""
    name: str           # Ten giai doan
    name_vn: str        # Ten tieng Viet
    kc: float           # He so Kc tai giai doan nay
    day_start: int      # Ngay bat dau (trong crop cycle)
    day_end: int        # Ngay ket thuc
    description: str    # Mo ta


@dataclass
class CropState:
    """Trang thai hien tai cua mo hinh cay trong."""
    stage: str = STAGE_INITIAL
    stage_name_vn: str = "Giai doan dau"
    kc: float = 0.4
    ks: float = 1.0       # Stress coefficient (1 - WSI)
    wsi: float = 0.0      # Water Stress Index [0, 1]
    et_crop: float = 0.0  # Evapotranspiration cay trong (mm/tick tương đối)
    crop_day: int = 1     # Ngay hien tai trong chu ky
    total_days: int = 90  # Tong so ngay chu ky
    progress_pct: float = 0.0  # Tien trinh %

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage":         self.stage,
            "stage_name_vn": self.stage_name_vn,
            "kc":            round(self.kc, 3),
            "ks":            round(self.ks, 3),
            "wsi":           round(self.wsi, 3),
            "et_crop":       round(self.et_crop, 4),
            "crop_day":      self.crop_day,
            "total_days":    self.total_days,
            "progress_pct":  round(self.progress_pct, 1),
        }


class CropModel:
    """
    Mo hinh cay trong theo FAO-56 + AquaCrop simplified.

    Tinh Kc theo giai doan, WSI theo do am dat,
    tra ve Ks va ET_crop de Environment Task dung.
    """

    def __init__(self, config):
        self._config = config

        # Lay cau hinh tu config module
        self._total_days = getattr(config, 'CROP_TOTAL_DAYS', 90)

        # Phan chia giai doan (FAO-56 Table 11, rau an la nhiet doi)
        # Tinh theo phan tram cua tong ngay
        pct_ini = getattr(config, 'CROP_PCT_INITIAL', 0.20)
        pct_dev = getattr(config, 'CROP_PCT_DEVELOPMENT', 0.30)
        pct_mid = getattr(config, 'CROP_PCT_MID', 0.30)
        # pct_late = 1 - pct_ini - pct_dev - pct_mid (tu dong)

        day_ini_end = int(self._total_days * pct_ini)
        day_dev_end = int(self._total_days * (pct_ini + pct_dev))
        day_mid_end = int(self._total_days * (pct_ini + pct_dev + pct_mid))

        # Kc values (FAO-56 Table 12, rau an la / salad crops)
        kc_ini = getattr(config, 'CROP_KC_INI', 0.4)
        kc_mid = getattr(config, 'CROP_KC_MID', 1.05)
        kc_end = getattr(config, 'CROP_KC_END', 0.55)

        self._stages = [
            CropStageInfo(
                name=STAGE_INITIAL,
                name_vn="Giai doan dau (cay con)",
                kc=kc_ini,
                day_start=1,
                day_end=day_ini_end,
                description="Cay moi trong, mat dat chua phu kin, thoat hoi nuoc thap"
            ),
            CropStageInfo(
                name=STAGE_DEVELOPMENT,
                name_vn="Phat trien (tru truong)",
                kc=0.0,  # Se noi suy tuyen tinh giua kc_ini va kc_mid
                day_start=day_ini_end + 1,
                day_end=day_dev_end,
                description="Cay tang truong nhanh, la phu dan, Kc tang tuyen tinh"
            ),
            CropStageInfo(
                name=STAGE_MID_SEASON,
                name_vn="Giua mua (truong thanh)",
                kc=kc_mid,
                day_start=day_dev_end + 1,
                day_end=day_mid_end,
                description="Cay truong thanh, thoat hoi nuoc toi da, nang suat cao nhat"
            ),
            CropStageInfo(
                name=STAGE_LATE_SEASON,
                name_vn="Cuoi mua (thu hoach)",
                kc=kc_end,
                day_start=day_mid_end + 1,
                day_end=self._total_days,
                description="Cay gia, la rung, thoat hoi nuoc giam dan"
            ),
        ]

        self._kc_ini = kc_ini
        self._kc_mid = kc_mid
        self._kc_end = kc_end

        # Soil water thresholds (FAO AquaCrop)
        self._theta_fc = getattr(config, 'CROP_THETA_FC', 65.0)   # Field Capacity (%)
        self._theta_wp = getattr(config, 'CROP_THETA_WP', 15.0)   # Wilting Point (%)
        # Ngưỡng bắt đầu stress (p = 0.55 cho rau, FAO-56 Table 22)
        self._p_depletion = getattr(config, 'CROP_P_DEPLETION', 0.55)

        # Trang thai
        self.state = CropState(total_days=self._total_days)

        logger.info(
            f"  [CROP] Mo hinh FAO-56 khoi tao: {self._total_days} ngay, "
            f"Kc_ini={kc_ini}, Kc_mid={kc_mid}, Kc_end={kc_end}, "
            f"FC={self._theta_fc}%, WP={self._theta_wp}%"
        )

    def update(self, sim_day: int, soil_moisture: float,
               light_norm: float, temperature: float,
               is_day: bool, dt_factor: float) -> CropState:
        """
        Cap nhat mo hinh cay trong moi tick.

        Args:
            sim_day:        Ngay mo phong hien tai (1-based)
            soil_moisture:  Do am dat hien tai (%)
            light_norm:     Anh sang chuyen hoa (0..1, = light / LIGHT_DAY_MAX)
            temperature:    Nhiet do (°C)
            is_day:         Co phai ban ngay khong
            dt_factor:      He so thoi gian (dt_real / TASK_INTERVAL)

        Returns:
            CropState voi Kc, WSI, Ks, ET_crop da cap nhat.
        """
        # 1. Xac dinh ngay trong chu ky (wrap quanh tong ngay)
        crop_day = ((sim_day - 1) % self._total_days) + 1
        self.state.crop_day = crop_day
        self.state.total_days = self._total_days
        self.state.progress_pct = (crop_day / self._total_days) * 100.0

        # 2. Tinh Kc theo giai doan
        kc = self._calc_kc(crop_day)
        self.state.kc = kc

        # 3. Tinh WSI (Water Stress Index)
        wsi = self._calc_wsi(soil_moisture)
        self.state.wsi = wsi
        self.state.ks = 1.0 - wsi

        # 4. Tinh ET_crop (relative evapotranspiration)
        #    ET_ref simplified = f(light, temperature)
        #    ET_actual = Ks × Kc × ET_ref
        if is_day and light_norm > 0:
            # ET_ref don gian hoa (Penman-Monteith simplified)
            et_ref = (
                light_norm * 0.06                          # Buc xa mat troi
                + max(0.0, (temperature - 15.0)) / 120.0   # Hieu ung nhiet do
            )
            et_crop = self.state.ks * kc * et_ref * dt_factor
        else:
            # Ban dem: thoat hoi nuoc rat thap (cuticular transpiration)
            et_crop = 0.005 * kc * dt_factor

        self.state.et_crop = et_crop

        return self.state

    def _calc_kc(self, crop_day: int) -> float:
        """
        Tinh he so Kc theo FAO-56.

        - Initial:     Kc = Kc_ini (hang so)
        - Development: Kc noi suy tuyen tinh tu Kc_ini den Kc_mid
        - Mid-season:  Kc = Kc_mid (hang so)
        - Late-season: Kc noi suy tuyen tinh tu Kc_mid den Kc_end
        """
        for stage in self._stages:
            if stage.day_start <= crop_day <= stage.day_end:
                self.state.stage = stage.name
                self.state.stage_name_vn = stage.name_vn

                if stage.name == STAGE_INITIAL:
                    return self._kc_ini

                elif stage.name == STAGE_DEVELOPMENT:
                    # Noi suy tuyen tinh (FAO-56 Eq. 66)
                    days_in = crop_day - stage.day_start
                    duration = stage.day_end - stage.day_start + 1
                    frac = days_in / max(1, duration - 1)
                    return self._kc_ini + (self._kc_mid - self._kc_ini) * frac

                elif stage.name == STAGE_MID_SEASON:
                    return self._kc_mid

                elif stage.name == STAGE_LATE_SEASON:
                    # Noi suy tuyen tinh giam
                    days_in = crop_day - stage.day_start
                    duration = stage.day_end - stage.day_start + 1
                    frac = days_in / max(1, duration - 1)
                    return self._kc_mid + (self._kc_end - self._kc_mid) * frac

        # Fallback (khong nen xay ra)
        return self._kc_mid

    def _calc_wsi(self, soil_moisture: float) -> float:
        """
        Tinh Water Stress Index theo FAO AquaCrop simplified.

        WSI = 0 khi am dat >= nguong RAW (Readily Available Water)
        WSI tang tuyen tinh len 1 khi am dat giam ve Wilting Point

        RAW = FC - p × (FC - WP)  (p = muc depletion cho phep)
        """
        theta = soil_moisture
        fc = self._theta_fc
        wp = self._theta_wp

        # Nguong bat dau stress (Readily Available Water)
        raw_threshold = fc - self._p_depletion * (fc - wp)

        if theta >= raw_threshold:
            # Du nuoc, khong stress
            return 0.0
        elif theta <= wp:
            # Heo hoan toan
            return 1.0
        else:
            # Stress tuyen tinh giua WP va RAW threshold
            return 1.0 - (theta - wp) / (raw_threshold - wp)

    def get_moisture_decay_factor(self) -> float:
        """
        Tra ve he so dieu chinh cho moisture decay.
        Kc cao -> bay hoi nhieu hon -> decay nhanh hon.
        Khi WSI cao, stomata dong -> giam thoat hoi nuoc.
        """
        return self.state.kc * self.state.ks

    def get_co2_uptake_factor(self) -> float:
        """
        He so hap thu CO2 cua cay.
        Khi stress nuoc, stomata dong -> giam quang hop -> CO2 giam it hon.
        Khi cay truong thanh (Kc cao), quang hop manh hon.
        """
        return self.state.kc * self.state.ks

    def get_transpiration_rate(self) -> float:
        """
        Toc do thoat hoi nuoc (mm tuong doi / tick).
        ET_actual da tinh xong trong update(), tra ve luon.
        """
        return self.state.et_crop

    def get_stage_info(self) -> Dict[str, Any]:
        """Tra ve thong tin giai doan hien tai (de hien thi tren dashboard)."""
        for stage in self._stages:
            if stage.name == self.state.stage:
                return {
                    "name": stage.name,
                    "name_vn": stage.name_vn,
                    "kc": round(self.state.kc, 3),
                    "day_start": stage.day_start,
                    "day_end": stage.day_end,
                    "description": stage.description,
                }
        return {"name": self.state.stage, "kc": round(self.state.kc, 3)}
