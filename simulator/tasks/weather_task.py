"""
Nha Kinh Thong Minh - Task Thoi Tiet Thuc (OpenWeatherMap)
=========================================================
Lay du lieu thoi tiet thuc te qua API de thay the cho ham random.
"""
import time
import logging
import requests
from tasks.base_task import BaseTask

logger = logging.getLogger("task.weather")

class WeatherTask(BaseTask):
    def __init__(self, greenhouse, config):
        self.greenhouse = greenhouse
        self.config = config
        self.run_count = 0
        self._last_time = 0
        self._interval = getattr(config, 'WEATHER_API_INTERVAL', 900)  # Mac dinh 15 phut thuc te

    def shutdown(self) -> None:
        pass

    def run(self):
        now = time.time()
        # Chay ngay lan dau, sau do doi _interval
        if now - self._last_time < self._interval and self.run_count > 0:
            return
            
        self._last_time = now
        self.run_count += 1
        
        api_key = getattr(self.config, 'OPENWEATHER_API_KEY', '')
        city = getattr(self.config, 'OPENWEATHER_CITY', 'Ho Chi Minh')
        
        if not api_key:
            # Neu khong co API key, he thong se tiep tuc dung random trong EnvironmentTask
            return
            
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                weather_main = data['weather'][0]['main'].lower()
                clouds = data.get('clouds', {}).get('all', 0) / 100.0
                rain = data.get('rain', {}).get('1h', 0)
                
                condition = 'clear'
                intensity = 0.0
                if 'rain' in weather_main or rain > 0:
                    condition = 'rainy'
                    # Uoc luong cuong do mua tu luong mua (mm/h)
                    intensity = min(1.0, rain / 10.0) if rain > 0 else 0.5
                elif 'clouds' in weather_main or clouds > 0.4:
                    condition = 'cloudy'
                
                # Cap nhat thoi tiet vao the gioi mo phong
                # Su kien thoi tiet nay se keo dai bang _interval quy doi ra phut mo phong
                end_minutes = self.greenhouse.get_sim_minutes_absolute() + (self._interval / 60) * self.config.TIME_SCALE
                self.greenhouse.set_weather(condition, clouds, intensity, end_minutes)
                
                logger.info(f"  [THOI TIET THUC] {city}: {condition.upper()} (Mây: {clouds:.0%}, Mưa: {intensity:.1f})")
            else:
                logger.warning(f"  [THOI TIET THUC] API Error {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.error(f"  [THOI TIET THUC] Loi ket noi API: {e}")
