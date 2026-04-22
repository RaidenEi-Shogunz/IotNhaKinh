"""
Nha Kinh Thong Minh - State Manager (Persistence)
===================================================
Tach rieng logic luu/doc trang thai Greenhouse ra khoi model chinh.
Dam bao Single Responsibility Principle:
  - Greenhouse: chi quan ly du lieu (data store)
  - GreenhouseStateManager: chi quan ly persistence (save/load)
"""

import os
import json
import logging

logger = logging.getLogger("state_manager")


class GreenhouseStateManager:
    """
    Quan ly luu va phuc hoi trang thai Greenhouse tu disk.
    
    Su dung atomic write (tmp file + os.replace) de tranh corrupt
    khi crash giua chung.
    """

    def __init__(self, greenhouse, state_file: str = "greenhouse_state.json") -> None:
        self.greenhouse = greenhouse
        self.state_file = state_file

    def save(self) -> None:
        """Luu toan bo trang thai vao file JSON (atomic write)."""
        try:
            state_data = self.greenhouse.get_internal_state()
            # Ghi file JSON theo phuong thuc atomic
            tmp_file = self.state_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, ensure_ascii=False)
            os.replace(tmp_file, self.state_file)
            logger.debug("Da luu snapshot xuong disk")
        except Exception as e:
            logger.error(f"Loi luu snapshot: {e}")

    def load(self) -> bool:
        """Nap lai trang thai tu file. Tra ve True neu thanh cong."""
        if not os.path.exists(self.state_file):
            return False
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.greenhouse.restore_internal_state(data)
            return True
        except Exception as e:
            logger.error(f"Loi nap snapshot: {e}")
            return False
