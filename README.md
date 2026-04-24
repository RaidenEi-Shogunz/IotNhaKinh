<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=28&duration=3000&pause=1000&color=22C55E&center=true&vCenter=true&width=600&lines=🌿+Nhà+Kính+Thông+Minh;IoT+Smart+Greenhouse+System;Giám+Sát+%26+Điều+Khiển+Nông+Nghiệp" alt="Typing SVG" />

<br/>

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-Adafruit_IO-FF6B35?style=for-the-badge&logo=mqtt&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6+-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![Chart.js](https://img.shields.io/badge/Chart.js-4.x-FF6384?style=for-the-badge&logo=chartdotjs&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?style=for-the-badge&logo=sqlite&logoColor=white)

<br/>

> **Hệ thống IoT mô phỏng nhà kính nông nghiệp thông minh** — Giả lập cảm biến, điều khiển tưới tiêu tự động theo ngưỡng, tích hợp AI nhận dạng tình trạng cây trồng, dashboard thời gian thực.

<br/>

[![Xem Demo](https://img.shields.io/badge/▶_Xem_Demo-Live_Dashboard-22C55E?style=for-the-badge)](dashboard/index.html)
[![Tài liệu](https://img.shields.io/badge/📄_Tài_liệu-Báo_cáo-6366F1?style=for-the-badge)](#báo-cáo--kiến-trúc)

</div>

---

## 📑 Mục lục

- [Tổng quan hệ thống](#-tổng-quan-hệ-thống)
- [Kiến trúc IoT](#-kiến-trúc-iot)
- [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [Thành phần chức năng](#-thành-phần-chức-năng)
  - [Lớp Cảm biến (Simulator)](#1-lớp-cảm-biến--môi-trường-simulator)
  - [Lớp MQTT](#2-lớp-kết-nối-mqtt)
  - [Lớp Điều khiển](#3-lớp-xử-lý--điều-khiển)
  - [Dashboard Web](#4-lớp-ứng-dụng--dashboard-web)
  - [Tích hợp AI](#5-tích-hợp-trí-tuệ-nhân-tạo)
  - [Cooperative Scheduler (RTOS-style)](#6-cooperative-scheduler-rtos-style)
- [Mô hình mô phỏng môi trường](#-mô-hình-mô-phỏng-môi-trường)
- [Logic điều khiển bơm](#-logic-điều-khiển-bơm)
- [Cài đặt & Chạy hệ thống](#-cài-đặt--chạy-hệ-thống)
- [Cấu hình](#-cấu-hình)
- [MQTT Topics](#-mqtt-topics)
- [Giao diện Dashboard](#-giao-diện-dashboard)
- [Xuất dữ liệu CSV](#-xuất-dữ-liệu-csv)
- [Công nghệ sử dụng](#-công-nghệ-sử-dụng)
- [Nhóm phát triển](#-nhóm-phát-triển)

---

## 🌱 Tổng quan hệ thống

**Nhà Kính Thông Minh** là hệ thống IoT mô phỏng hoàn chỉnh cho bài toán giám sát và điều khiển nông nghiệp thông minh, **không cần phần cứng thật**. Toàn bộ dữ liệu cảm biến được sinh ra bằng phần mềm Python với mô hình toán học phản ánh thực tế (chu kỳ ngày-đêm, hiệu ứng tưới nước, biến động ngẫu nhiên).

### ✨ Tính năng nổi bật

| Tính năng | Mô tả |
|-----------|-------|
| 🌡️ **5 loại cảm biến ảo** | Độ ẩm đất, Nhiệt độ, Ánh sáng, Độ ẩm KK, CO₂ |
| 🔄 **Chu kỳ ngày-đêm** | Mô phỏng thay đổi thực tế theo thời gian 24h |
| 💧 **Điều khiển bơm ảo** | Tự động (ngưỡng) + Thủ công (dashboard) |
| 📡 **MQTT real-time** | Kết nối Adafruit IO, pub/sub đầy đủ |
| 📊 **Dashboard đẹp** | Biểu đồ Chart.js, Dark/Light mode, responsive |
| 🤖 **AI nhận dạng cây** | Google Teachable Machine — bình thường/thiếu nước/sâu bệnh |
| 🗄️ **SQLite logging** | Lưu lịch sử tưới, xuất CSV |
| 🐳 **Docker Compose** | Deploy một lệnh, môi trường cô lập |
| ⚙️ **Cooperative Scheduler** | Kiến trúc RTOS-style với các task độc lập |

---

## 🏗️ Kiến trúc IoT

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER (Lớp Cảm nhận)                  │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Độ ẩm đất   │  │  Nhiệt độ   │  │  Ánh sáng   │               │
│  │  (Virtual)   │  │  (Virtual)   │  │  (Virtual)   │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                  │                  │                       │
│  ┌──────┴──────────────────┴──────────────────┴──────┐               │
│  │         greenhouse.py — Environment Simulator      │               │
│  │   (Mô hình toán học: sin cycle + pump effect)      │               │
│  └──────────────────────────┬─────────────────────────┘               │
└─────────────────────────────│───────────────────────────────────────-─┘
                              │ MQTT Publish
┌─────────────────────────────▼─────────────────────────────────────────┐
│                   NETWORK LAYER (Lớp Mạng)                             │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │                    MQTT Broker (Adafruit IO)                  │       │
│  │                                                               │       │
│  │  farm/greenhouse/soil_moisture    ◄──► Độ ẩm đất             │       │
│  │  farm/greenhouse/temperature      ◄──► Nhiệt độ KK           │       │
│  │  farm/greenhouse/light            ◄──► Cường độ ánh sáng     │       │
│  │  farm/greenhouse/humidity         ◄──► Độ ẩm không khí       │       │
│  │  farm/greenhouse/co2              ◄──► Nồng độ CO₂           │       │
│  │  farm/greenhouse/pump/status      ◄──► Trạng thái bơm        │       │
│  │  farm/greenhouse/pump/cmd         ◄──► Lệnh điều khiển bơm   │       │
│  └─────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
                              │ MQTT Subscribe
┌─────────────────────────────▼─────────────────────────────────────────┐
│                  PROCESSING LAYER (Lớp Xử lý)                          │
│                                                                         │
│  ┌────────────────────┐   ┌────────────────────┐                       │
│  │   state_manager.py  │   │    scheduler.py     │                       │
│  │  - Quản lý ngưỡng  │   │  - Task simulator   │                       │
│  │  - Logic bơm auto  │   │  - Task MQTT pub     │                       │
│  │  - Ghi log SQLite  │   │  - Task control      │                       │
│  └────────────────────┘   │  - Task AI           │                       │
│                            └────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────────┘
                              │ WebSocket / HTTP
┌─────────────────────────────▼─────────────────────────────────────────┐
│                 APPLICATION LAYER (Lớp Ứng dụng)                        │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────┐        │
│  │                    Dashboard Web (SPA)                        │        │
│  │                                                               │        │
│  │   📊 Biểu đồ thời gian thực    🎛️ Điều khiển bơm           │        │
│  │   📋 Nhật ký tưới tiêu          ⚠️ Cảnh báo alerts          │        │
│  │   🤖 AI nhận dạng cây           🌙 Dark / Light mode         │        │
│  │   📥 Xuất dữ liệu CSV           📱 Responsive mobile         │        │
│  └────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Cấu trúc thư mục

```
IotNhaKinh/
│
├── 📄 docker-compose.yml        # Orchestrate toàn bộ hệ thống
├── 📄 Dockerfile                # Image cho Python simulator
├── 📄 pyproject.toml            # Cấu hình Python project
├── 📄 .dockerignore             # Loại file không copy vào Docker
├── 📄 .gitignore
│
├── 🐍 simulator/                # Lõi Python — Bộ mô phỏng & điều khiển
│   ├── main.py                  # Entry point — khởi động scheduler
│   ├── greenhouse.py            # ⭐ Mô hình môi trường nhà kính
│   ├── scheduler.py             # ⭐ Cooperative task scheduler (RTOS-style)
│   ├── state_manager.py         # ⭐ Quản lý trạng thái & điều khiển bơm
│   ├── __init__.py
│   └── requirements.txt         # paho-mqtt, sqlite3, ...
│
└── 🌐 dashboard/                # Frontend — Dashboard web
    ├── index.html               # Trang chính SPA
    ├── style.css                # ⭐ Thiết kế glassmorphism, dark/light mode
    ├── chart.js                 # ⭐ Biểu đồ Chart.js — sensor & moisture
    ├── config.js                # Cấu hình toàn cục, state, DOM refs
    ├── utils.js                 # Hàm tiện ích (debounce, escapeHtml)
    ├── mqtt.js                  # Kết nối MQTT.js WebSocket
    ├── ui.js                    # Cập nhật UI — gauges, bảng, alerts
    └── app.js                   # Entry point frontend
```

---

## 🔧 Thành phần chức năng

### 1. Lớp Cảm biến & Môi trường (Simulator)

**File:** `simulator/greenhouse.py`

Module này là trái tim của hệ thống mô phỏng. Toàn bộ dữ liệu cảm biến được sinh bằng mô hình toán học, không cần phần cứng.

#### Mô hình sinh dữ liệu

```python
# Chu kỳ ngày-đêm (sin wave)
hour = datetime.now().hour + datetime.now().minute / 60
day_progress = (hour - 6) / 12  # 0..1 từ 6h đến 18h

# Nhiệt độ: 18°C ban đêm → 35°C ban ngày
temperature = 18 + 17 * max(0, sin(π * day_progress))

# Ánh sáng: 0 lux ban đêm → 10000 lux buổi trưa
light = max(0, 10000 * sin(π * day_progress))

# Độ ẩm đất: giảm dần theo thời gian, tăng khi bơm bật
soil_moisture -= EVAPORATION_RATE * delta_t
if pump_is_on:
    soil_moisture += PUMP_RATE * delta_t

# Nhiễu ngẫu nhiên thực tế
temperature += random.gauss(0, 0.3)
```

#### Thông số cảm biến

| Cảm biến | Đơn vị | Ban ngày | Ban đêm | Khi bơm bật |
|----------|--------|----------|---------|-------------|
| Độ ẩm đất | % | 20–65% | 20–65% | +2%/s |
| Nhiệt độ KK | °C | 25–38°C | 15–22°C | — |
| Ánh sáng | lux | 5000–12000 | 0–100 | — |
| Độ ẩm KK | % | 45–70% | 65–85% | +5% |
| CO₂ | ppm | 400–800 | 350–600 | — |

---

### 2. Lớp Kết nối MQTT

**File:** `simulator/scheduler.py` (task MQTT) + `dashboard/mqtt.js`

#### Python Simulator → Adafruit IO

```python
import paho.mqtt.client as mqtt

BROKER   = "io.adafruit.com"
PORT     = 1883
USERNAME = "your_username"
API_KEY  = "your_aio_key"

# Topics publish
TOPIC_MOISTURE    = f"{USERNAME}/feeds/farm.greenhouse.soil-moisture"
TOPIC_TEMPERATURE = f"{USERNAME}/feeds/farm.greenhouse.temperature"
TOPIC_PUMP_STATUS = f"{USERNAME}/feeds/farm.greenhouse.pump-status"
TOPIC_PUMP_CMD    = f"{USERNAME}/feeds/farm.greenhouse.pump-cmd"   # subscribe
```

#### Dashboard → Adafruit IO (WebSocket)

```javascript
// dashboard/mqtt.js
const client = mqtt.connect('wss://io.adafruit.com/mqtt', {
    username: CONFIG.adafruitUser,
    password: CONFIG.adafruitKey,
});

client.subscribe(`${user}/feeds/farm.greenhouse.+`);
client.publish(`${user}/feeds/farm.greenhouse.pump-cmd`, 'ON');
```

---

### 3. Lớp Xử lý & Điều khiển

**File:** `simulator/state_manager.py`

Module quản lý toàn bộ logic điều khiển bơm và ghi log.

#### Logic điều khiển tự động

```
┌───────────────────────────────────┐
│    Nhận dữ liệu soil_moisture      │
└──────────────┬────────────────────┘
               │
        soil_moisture < threshold_low?
               │
        ┌──────┴──────┐
       YES            NO
        │              │
   BẬT BƠM        soil_moisture > threshold_high?
   publish ON           │
                  ┌─────┴─────┐
                 YES          NO
                  │            │
             TẮT BƠM      GIỮ NGUYÊN
             publish OFF   (không đổi)
```

#### Ghi log SQLite

```sql
-- Bảng lịch sử tưới
CREATE TABLE watering_log (
    id        INTEGER PRIMARY KEY,
    timestamp TEXT,
    duration  REAL,         -- giây
    moisture_start REAL,
    moisture_end   REAL,
    trigger   TEXT          -- 'AUTO' | 'MANUAL'
);

-- Bảng cảm biến theo thời gian
CREATE TABLE sensor_history (
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,
    moisture    REAL,
    temperature REAL,
    light       REAL,
    humidity    REAL,
    co2         REAL
);
```

---

### 4. Lớp Ứng dụng — Dashboard Web

**Thư mục:** `dashboard/`

Dashboard được xây dựng dạng **Single Page Application** thuần HTML/CSS/JS, không cần framework, nhẹ và nhanh.

#### Tính năng giao diện

**🎯 Sensor Cards với Gauge tròn**
- 5 card hiển thị giá trị real-time với animation
- Vòng tròn SVG (`stroke-dashoffset`) biến thiên mượt mà
- Màu sắc phân biệt: xanh dương (độ ẩm), đỏ (nhiệt), vàng (ánh sáng), cyan (KK), tím (CO₂)

**📊 Biểu đồ Chart.js**
- **Biểu đồ độ ẩm đất** (cố định, luôn hiển thị)
- **Biểu đồ phụ** (chuyển tab: nhiệt độ / ánh sáng / độ ẩm KK / CO₂)
- Skeleton loading khi chờ dữ liệu
- Debounce 100ms để tránh re-render quá nhiều

**🎛️ Bảng điều khiển bơm**
```
┌──────────────────────────────┐
│  💧  PUMP STATUS             │
│  ●  ĐANG HOẠT ĐỘNG           │  ← Water wave animation
│                              │
│  [  AUTO  ] [  MANUAL  ]     │  ← Chế độ
│  [    BẬT BƠM    ]           │  ← Nút điều khiển
│                              │
│  Ngưỡng độ ẩm: [====●====]   │  ← Slider 10–90%
│  Thấp: 30%  |  Cao: 70%      │
└──────────────────────────────┘
```

**⚠️ Bảng cảnh báo (Alerts)**
- 3 mức: `INFO` (xanh) / `WARNING` (vàng) / `DANGER` (đỏ)
- Cảnh báo khi độ ẩm quá thấp, nhiệt độ quá cao, CO₂ vượt ngưỡng

**📋 Nhật ký tưới**
- Bảng lịch sử các lần bơm: thời gian, thời lượng, trigger
- Cuộn nội bộ, max 280px

**🌙 Dark / Light Mode**
- CSS custom properties (`--bg-primary`, `--text-primary`, v.v.)
- Toggle bằng nút ☀️/🌙 trên header
- Lưu preference vào `localStorage`

---

### 5. Tích hợp Trí tuệ Nhân tạo

**Công nghệ:** Google Teachable Machine (Image Classification)

#### Quy trình huấn luyện

```
1. Thu thập dữ liệu ảnh
   ├── Class 1: "Bình thường"   (~100 ảnh — cây xanh, lá đều)
   ├── Class 2: "Thiếu nước"    (~100 ảnh — lá héo, màu vàng)
   └── Class 3: "Sâu bệnh"     (~100 ảnh — lá đốm, lỗ thủng)

2. Huấn luyện trên Teachable Machine
   └── Export model TensorFlow.js

3. Tích hợp dashboard
   └── Load model → dự đoán từ camera/ảnh upload
```

#### Ảnh hưởng đến điều khiển

```javascript
// dashboard/ai-integration.js
switch (prediction.className) {
    case 'Thiếu nước':
        // Hạ ngưỡng → bơm sớm hơn
        CONFIG.moistureThresholdLow += 10;
        mqtt.publish(TOPIC_PUMP_CMD, 'ON');
        break;
    case 'Sâu bệnh':
        // Cảnh báo, không thay đổi tưới
        addAlert('WARNING', 'Phát hiện dấu hiệu sâu bệnh!');
        break;
    case 'Bình thường':
        // Giữ nguyên cài đặt
        break;
}
```

| Kết quả AI | Hành động hệ thống |
|------------|-------------------|
| 🌿 Bình thường | Giữ nguyên ngưỡng mặc định |
| 🥀 Thiếu nước | Tăng ngưỡng 10%, bật bơm ngay |
| 🐛 Sâu bệnh | Gửi cảnh báo DANGER, không đổi tưới |

---

### 6. Cooperative Scheduler (RTOS-style)

**File:** `simulator/scheduler.py`

Hệ thống tổ chức theo mô hình **Cooperative Multitasking**, chia chức năng thành các task độc lập, lần lượt thực thi theo vòng lặp chính.

```python
class Task:
    def __init__(self, name, func, interval_ms):
        self.name        = name
        self.func        = func
        self.interval    = interval_ms / 1000
        self.last_run    = 0

class CoopScheduler:
    def __init__(self):
        self.tasks = []

    def add_task(self, name, func, interval_ms):
        self.tasks.append(Task(name, func, interval_ms))

    def run_forever(self):
        while True:
            now = time.time()
            for task in self.tasks:
                if now - task.last_run >= task.interval:
                    task.func()
                    task.last_run = now
            time.sleep(0.05)  # 50ms yield
```

#### Bảng phân chia Task

| Task | Chức năng | Chu kỳ |
|------|-----------|--------|
| `task_simulate` | Cập nhật giá trị cảm biến ảo | 1 giây |
| `task_mqtt_publish` | Publish dữ liệu lên Adafruit IO | 3 giây |
| `task_control` | So sánh ngưỡng, điều khiển bơm | 2 giây |
| `task_log` | Ghi lịch sử vào SQLite | 10 giây |
| `task_ai` | Nhận kết quả AI, điều chỉnh ngưỡng | 30 giây |

```
Timeline (mỗi ô = 1 giây):
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│  1s  │  2s  │  3s  │  4s  │  5s  │  6s  │  7s  │
├──────┼──────┼──────┼──────┼──────┼──────┼──────┤
│ SIM  │ SIM  │ SIM  │ SIM  │ SIM  │ SIM  │ SIM  │  ← task_simulate (1s)
│      │ CTRL │      │ CTRL │      │ CTRL │      │  ← task_control  (2s)
│      │      │ MQTT │      │      │ MQTT │      │  ← task_mqtt_pub (3s)
│      │      │      │      │      │      │      │
│                  LOG (10s)                      │  ← task_log     (10s)
└──────────────────────────────────────────────────┘
```

---

## 🌤️ Mô hình mô phỏng môi trường

### Chu kỳ ngày-đêm

```
Nhiệt độ (°C)
  38 │         ╭───╮
  30 │       ╭╯   ╰╮
  22 │     ╭╯       ╰╮
  18 │──╭──╯           ╰──────
     └──────────────────────────→ Giờ
     0   6   9   12  15  18  24
         ↑           ↑
       Bình minh   Hoàng hôn

Ánh sáng (lux)
12000│          ╭─╮
8000 │        ╭╯   ╰╮
4000 │      ╭╯       ╰╮
   0 │──────╯           ╰───────
     0   6   9   12  15  18  24
```

### Hiệu ứng tưới nước lên độ ẩm

```
Độ ẩm đất (%)
  80 │            ╭───╮
  60 │          ╭╯     │
  40 │────────╭╯       │──────────
  30 │  NGƯỠNG│         │ NGƯỠNG
  20 │        ↑ Bơm bật ↓ Bơm tắt
     └──────────────────────────────→ Thời gian
         Bay hơi   Tưới   Bay hơi
         (giảm)   (tăng)  (giảm)
```

---

## 💧 Logic điều khiển bơm

### Chế độ AUTO (Ngưỡng)

```
Bắt đầu
   │
   ▼
Đọc soil_moisture từ simulator
   │
   ├─ moisture < LOW_THRESHOLD (30%)? ──► BẬT BƠM ──► Publish "ON"
   │                                                       │
   ├─ moisture > HIGH_THRESHOLD (70%)? ─► TẮT BƠM ──► Publish "OFF"
   │
   └─ Trong khoảng [30%, 70%] ──────────► Giữ nguyên trạng thái
```

### Chế độ MANUAL (Tay)

Người dùng nhấn **"BẬT BƠM"** trên dashboard → Dashboard publish lệnh `ON` lên `pump/cmd` → Simulator nhận → Cập nhật trạng thái bơm → Publish `pump/status = ON` → Dashboard cập nhật UI.

```
User Click        MQTT Pub          Simulator         MQTT Pub        Dashboard
[BẬT BƠM]  ──► pump/cmd=ON  ──►  Nhận lệnh    ──►  pump/status  ──►  Cập nhật UI
                                  bật bơm ảo         = RUNNING         💧 Đang tưới
```

---

## 🚀 Cài đặt & Chạy hệ thống

### Yêu cầu

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Docker + Docker Compose)
- Tài khoản [Adafruit IO](https://io.adafruit.com/) (miễn phí)
- Trình duyệt hiện đại (Chrome, Firefox, Edge)

### Bước 1: Clone repository

```bash
git clone https://github.com/RaidenEi-Shogunz/IotNhaKinh.git
cd IotNhaKinh
```

### Bước 2: Tạo tài khoản Adafruit IO & lấy API Key

1. Đăng ký tại [io.adafruit.com](https://io.adafruit.com)
2. Vào **My Key** → Copy `Username` và `Active Key`
3. Tạo Group feed tên `farm` > `greenhouse`

### Bước 3: Cấu hình thông tin xác thực

Tạo file `.env` ở thư mục gốc:

```env
# Adafruit IO credentials
ADAFRUIT_USERNAME=your_username
ADAFRUIT_API_KEY=your_aio_key

# Ngưỡng điều khiển (mặc định)
MOISTURE_LOW_THRESHOLD=30
MOISTURE_HIGH_THRESHOLD=70

# Thời gian mô phỏng (1 = thực tế, 60 = x60 lần)
TIME_MULTIPLIER=1
```

Cập nhật file `dashboard/config.js`:

```javascript
export const CONFIG = {
    adafruitUser: 'your_username',   // ← Thay vào đây
    adafruitKey:  'your_aio_key',    // ← Thay vào đây
    // ...
};
```

### Bước 4: Chạy với Docker Compose

```bash
# Build và khởi động toàn bộ hệ thống
docker compose up --build

# Chạy nền (detached)
docker compose up -d --build

# Xem log real-time
docker compose logs -f simulator
```

**Đầu ra kỳ vọng:**

```
simulator-1  | 🌿 Nhà Kính Thông Minh — Khởi động...
simulator-1  | ✅ Kết nối MQTT thành công: io.adafruit.com
simulator-1  | 🔄 Khởi động Cooperative Scheduler...
simulator-1  |
simulator-1  | [task_simulate]  ⏱  00:00:01 | 💧 Độ ẩm: 45.2% | 🌡  24.3°C | ☀  3200 lux
simulator-1  | [task_control]   🔴 Bơm OFF | Độ ẩm 45.2% trong ngưỡng [30%, 70%]
simulator-1  | [task_mqtt_pub]  📡 Publish → farm/greenhouse/soil_moisture = 45.2
```

### Bước 5: Mở Dashboard

```bash
# Mở file trực tiếp trên trình duyệt
open dashboard/index.html

# Hoặc dùng Live Server (VS Code Extension)
# Cài: ms-vscode.live-server
# Click chuột phải index.html → "Open with Live Server"
```

> **Lưu ý:** Dashboard kết nối trực tiếp đến Adafruit IO qua MQTT WebSocket — không cần backend riêng.

---

## ⚙️ Cấu hình

### Thông số môi trường (`simulator/greenhouse.py`)

```python
# Tốc độ bay hơi (% độ ẩm mất đi mỗi giây)
EVAPORATION_RATE = 0.05

# Tốc độ tăng độ ẩm khi bơm hoạt động (%/giây)
PUMP_RATE = 0.5

# Biên độ nhiễu ngẫu nhiên
NOISE_TEMPERATURE = 0.3   # ±°C
NOISE_MOISTURE    = 0.2   # ±%
NOISE_LIGHT       = 100   # ±lux

# Nhiệt độ ban ngày / ban đêm
TEMP_NIGHT = 18   # °C
TEMP_DAY   = 35   # °C

# Ánh sáng tối đa (buổi trưa)
LIGHT_MAX  = 10000  # lux
```

### Ngưỡng điều khiển (`simulator/state_manager.py`)

```python
DEFAULT_CONFIG = {
    'moisture_low':  30,   # % — dưới mức này → bật bơm
    'moisture_high': 70,   # % — trên mức này → tắt bơm
    'temp_alert':    38,   # °C — cảnh báo nóng
    'co2_alert':     800,  # ppm — cảnh báo CO₂ cao
}
```

---

## 📡 MQTT Topics

| Topic | Kiểu | Mô tả | Ví dụ payload |
|-------|------|-------|---------------|
| `farm/greenhouse/soil_moisture` | Publish | Độ ẩm đất (%) | `45.2` |
| `farm/greenhouse/temperature` | Publish | Nhiệt độ KK (°C) | `27.4` |
| `farm/greenhouse/light` | Publish | Ánh sáng (lux) | `6500` |
| `farm/greenhouse/humidity` | Publish | Độ ẩm KK (%) | `62.0` |
| `farm/greenhouse/co2` | Publish | CO₂ (ppm) | `520` |
| `farm/greenhouse/pump/status` | Publish | Trạng thái bơm | `ON` / `OFF` |
| `farm/greenhouse/pump/cmd` | Subscribe | Lệnh điều khiển | `ON` / `OFF` / `AUTO` |
| `farm/greenhouse/threshold` | Subscribe | Cập nhật ngưỡng | `{"low":30,"high":70}` |
| `farm/greenhouse/alerts` | Publish | Cảnh báo hệ thống | `{"level":"WARNING","msg":"..."}` |

---

## 🖥️ Giao diện Dashboard

### Dark Mode (Mặc định)

```
┌─────────────────────────────────────────────────────────┐
│ 🌿 NHÀ KÍNH THÔNG MINH  ● ONLINE  🕐 14:32:15   ☀ 🌙 │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ╔═══════╗  ╔═══════╗  ╔═══════╗  ╔═══════╗  ╔═══════╗ │
│  ║ 💧45% ║  ║ 🌡27° ║  ║ ☀6500 ║  ║ 💨62% ║  ║🌫520  ║ │
│  ║  〇   ║  ║  〇   ║  ║  〇   ║  ║  〇   ║  ║  〇  ║ │
│  ║ BÌNH  ║  ║NÓNG VB║  ║SÁNG VB║  ║ BT    ║  ║ BT   ║ │
│  ╚═══════╝  ╚═══════╝  ╚═══════╝  ╚═══════╝  ╚═══════╝ │
│                                                           │
│  ┌─────────────────────────────┐  ┌───────────────────┐  │
│  │ 📊 Biểu đồ độ ẩm đất       │  │ 🎛 Điều khiển bơm │  │
│  │                             │  │  💧 ĐANG TẮT       │  │
│  │  ~~~~~~~~~~~~~~~~~~~~       │  │  [AUTO] [MANUAL]   │  │
│  │                             │  │  [  BẬT BƠM  ]     │  │
│  │ [Nhiệt độ][Ánh sáng][CO2]  │  │  Ngưỡng: ══●══ 30% │  │
│  │  ~~~~~~~~~~~~~~~~~~~~       │  │  🤖 AI: Bình thường │  │
│  └─────────────────────────────┘  └───────────────────┘  │
│                                                           │
│  ┌──────────────────────┐  ┌──────────────────────────┐  │
│  │ 📋 Nhật ký tưới      │  │ ⚠️ Cảnh báo              │  │
│  │ 14:20 | 3m | AUTO    │  │ ⚠ Độ ẩm thấp — 14:22    │  │
│  │ 13:45 | 2m | MANUAL  │  │ ℹ Kết nối MQTT — 14:00  │  │
│  └──────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Responsive Mobile

- **≥ 1024px**: Layout 2 cột (biểu đồ + điều khiển)
- **768px – 1024px**: Stack dọc, biểu đồ full-width
- **≤ 480px**: 2 cột card cảm biến, header compact

---

## 📥 Xuất dữ liệu CSV

Dashboard hỗ trợ xuất toàn bộ dữ liệu lịch sử ra file CSV:

```
Nút [📥 Xuất CSV] → Tải file: nhakinh_2025-01-15.csv
```

**Định dạng file:**

```csv
Thời gian,Độ ẩm đất (%),Nhiệt độ (C),Ánh sáng (lux),Độ ẩm KK (%),CO2 (ppm)
14:30:01,45.2,27.4,6500,62.0,520
14:30:04,44.9,27.5,6520,62.1,518
14:30:07,80.1,27.5,6510,64.5,515
```

> Dữ liệu có BOM UTF-8 (`\uFEFF`) để mở đúng tiếng Việt trong Excel.

---

## 🛠️ Công nghệ sử dụng

| Lớp | Công nghệ | Mục đích |
|-----|-----------|---------|
| **Simulator** | Python 3.11 | Mô phỏng môi trường, logic điều khiển |
| **MQTT Client** | paho-mqtt 2.x | Kết nối broker từ Python |
| **MQTT Broker** | Adafruit IO | Cloud MQTT broker miễn phí |
| **Database** | SQLite 3 | Lưu log cảm biến & tưới tiêu |
| **Frontend** | HTML5 / CSS3 / ES6 | Dashboard web SPA |
| **Charts** | Chart.js 4.x | Biểu đồ đường real-time |
| **MQTT Web** | MQTT.js (WebSocket) | Kết nối MQTT từ trình duyệt |
| **AI** | TensorFlow.js + Teachable Machine | Nhận dạng tình trạng cây |
| **Container** | Docker + Docker Compose | Deploy & orchestration |
| **Font** | Google Fonts — Inter | Typography |

---

## 📊 Hiệu năng & Giới hạn

| Chỉ số | Giá trị |
|--------|---------|
| Tần suất publish MQTT | 1 message / 3 giây / feed |
| Độ trễ cập nhật Dashboard | < 500ms |
| Giới hạn dữ liệu biểu đồ | 100 điểm gần nhất |
| Giới hạn Adafruit IO (Free) | 30 msg/phút, 5 feeds active |
| Dung lượng SQLite (1 ngày) | ~5 MB |

---

## 🐛 Xử lý sự cố

<details>
<summary><strong>❌ Dashboard không nhận dữ liệu</strong></summary>

1. Kiểm tra `CONFIG.adafruitUser` và `CONFIG.adafruitKey` trong `dashboard/config.js`
2. Mở DevTools → Console xem lỗi MQTT
3. Xác nhận feed names khớp giữa Python và dashboard
4. Kiểm tra giới hạn rate Adafruit IO (30 msg/phút)

</details>

<details>
<summary><strong>❌ Docker container không start</strong></summary>

```bash
# Xem log chi tiết
docker compose logs simulator

# Rebuild từ đầu
docker compose down --volumes
docker compose up --build --force-recreate
```

</details>

<details>
<summary><strong>❌ Bơm không tự động bật</strong></summary>

1. Kiểm tra chế độ đang ở **AUTO** (không phải MANUAL)
2. Xem ngưỡng trên slider — mặc định `LOW = 30%`
3. Đợi `task_control` chạy (mỗi 2 giây)
4. Xem log: `[task_control] 🔴 Bơm OFF | Độ ẩm...`

</details>

---

## 👨‍💻 Nhóm phát triển

<div align="center">

| Thành viên | Vai trò | GitHub |
|------------|---------|--------|
| RaidenEi-Shogunz | Lead Developer | [@RaidenEi-Shogunz](https://github.com/RaidenEi-Shogunz) |

**Đề tài 2 — Hệ thống giám sát nông nghiệp giả lập "Nhà kính thông minh"**

*Môn: Internet of Things — Hệ thống nhúng*

</div>

---

## 📜 Giấy phép

```
MIT License — Tự do sử dụng, chỉnh sửa và phân phối với điều kiện giữ nguyên thông báo bản quyền.
```

---

<div align="center">

**🌿 Nhà Kính Thông Minh** — *Nông nghiệp 4.0, không cần phần cứng*

Made with ❤️ and ☕ | IoT Smart Greenhouse Simulation System

⭐ Nếu project hữu ích, hãy cho một ngôi sao nhé!

</div>
