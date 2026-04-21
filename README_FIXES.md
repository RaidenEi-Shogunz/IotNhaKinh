# Bao cao sua loi - Nha Kinh Thong Minh IoT

## Van de chinh: MQTT disconnect/reconnect lien tuc

### Nguyen nhan goc re
Adafruit IO Free tier gioi han 30 data points/phut.
- Simulator publish 9 feeds moi 15 giay = **36 feeds/phut > 30 limit**
- Khi vuot limit, Adafruit IO ngat TCP ket noi Python
- Dashboard mat feed, hien thi "mat ket noi", reconnect sau 5 giay
- Moi reconnect lai burst them tin nhan -> vong lap vo tan

---

## Danh sach cac loi da sua

### simulator/config.py
| Truoc | Sau | Ly do |
|-------|-----|-------|
| RATE_LIMIT_MIN_INTERVAL = 15 | = 22 | 9 x (60/22) = 24.5/phut < 30 |
| TASK_INTERVAL_MQTT = 15 | = 22 | Dong bo voi rate limit |

### simulator/tasks/mqtt_task.py
- **Sliding window rate limiter**: dem chinh xac so publish trong 60 giay qua
- **rc=141 detection**: log canh bao ro rang khi Adafruit IO ngat vi rate limit
- **Offline queue flush co delay 250ms**: tranh burst 7 tin cung luc khi reconnect
- **QoS 0 khi subscribe**: giam overhead (khong can QoS 1 cho lenh dieu khien)
- **PID data trong AI payload**: publish pid_output + pid_setpoint de dashboard hien thi
- **Per-publish rate check**: moi feed duoc kiem tra truoc khi gui

### dashboard/js/app.js
| Loi | Fix |
|-----|-----|
| reconnectPeriod: 5000 (qua ngan) | = 15000ms |
| Khong co keepalive | them keepalive: 60 |
| Subscribe khong co options | { qos: 0 } |
| PID display khong cap nhat | lay tu ai.pid_output / ai.pid_setpoint |
| Khong co trang thai 'reconnecting' | updateConnectionStatus('reconnecting') |
| Chart memory leak khi doi theme | destroy() truoc khi tao moi |
| Fallback clock drift | chi chay khi > 60s chua co MQTT sync |

### dashboard/css/style.css
- Them class `.status-dot.reconnecting` (mau vang)
- Them bien `--color-pump-on` / `--color-pump-off` cho nhat ky tuoi

### dashboard/index.html
- Pin mqtt.js version cu the: `mqtt@5.3.4` (tranh breaking changes)
- Pin chart.js: `chart.js@4.4.3/dist/chart.umd.min.js`

---

## Cach chay

```bash
cd simulator
pip install -r requirements.txt
python main.py
```

Mo `dashboard/index.html` bang trinh duyet (double-click hoac `Live Server`)

**Luong hoat dong chinh xac:**
```
CMD (Python simulator)           Dashboard (Browser)
  |                                    |
  |-- publish soil-moisture ---------> |-- hien thi gauge do am
  |-- publish temperature -----------> |-- hien thi gauge nhiet do
  |-- publish ai-status (JSON) ------> |-- hien thi AI + PID + dong ho
  |-- publish watering-event -------> |-- cap nhat nhat ky tuoi
  |                                    |
  |<-- subscribe pump-cmd ----------- |-- nut bat/tat bom
  |<-- subscribe greenhouse-mode ---- |-- chuyen AUTO/MANUAL
  |<-- subscribe moisture-threshold - |-- chinh nguong do am
```
