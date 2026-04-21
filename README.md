# Nha Kinh Thong Minh - Smart Greenhouse IoT Simulation

Hệ thống IoT mô phỏng giám sát và điều khiển tưới tiêu nhà kính thông minh sử dụng MQTT và Adafruit IO.

## Tính năng chính

- **Mô phỏng môi trường thời gian thực**: Nhiệt độ, độ ẩm đất, ánh sáng, CO2, thời tiết
- **Điều khiển bơm thông minh**: PID controller + ngưỡng threshold
- **Dashboard web**: Giao diện trực quan với biểu đồ thời gian thực
- **Cảnh báo**: Phát hiện vấn đề và gửi thông báo
- **Lưu trữ dữ liệu**: SQLite database cho lịch sử
- **AI phân tích**: Đánh giá tình trạng cây trồng

## Kiến trúc hệ thống

```
┌─────────────────┐    MQTT     ┌─────────────────┐
│   Dashboard     │◄──────────►│   Adafruit IO   │
│  (HTML/CSS/JS)  │             │    Broker       │
└─────────────────┘             └─────────────────┘
         ▲                              ▲
         │                              │
         └──────────────────────────────┘
                    MQTT
                    ▼
           ┌─────────────────┐
           │   Simulator     │
           │   (Python)      │
           │                 │
           │ ┌─────────────┐ │
           │ │ Greenhouse  │ │ ◄── Shared State
           │ │   Model     │ │
           │ └─────────────┘ │
           │                 │
           │ ┌─────────────┐ │
           │ │ Scheduler   │ │ ◄── Cooperative Tasks
           │ │ (Async)     │ │
           │ └─────────────┘ │
           │                 │
           │ Tasks:          │
           │ • Environment   │
           │ • Pump Control  │
           │ • MQTT Publish  │
           │ • AI Analysis   │
           │ • Alerts        │
           │ • Persistence   │
           └─────────────────┘
```

## Cài đặt và chạy

### Yêu cầu hệ thống

- Python 3.8+
- Trình duyệt web hiện đại
- Tài khoản Adafruit IO (free tier)

### 1. Cài đặt thư viện Python

```bash
cd simulator
pip install -r requirements.txt
```

### 2. Cấu hình credentials Adafruit IO

```bash
cp .env.example .env
```

Mở file `.env` và điền thông tin:
```
ADAFRUIT_USERNAME=ten_tai_khoan_cua_ban
ADAFRUIT_KEY=aio_xxxxxxxxxxxxxxxxxx
```

### 3. Chạy simulator

```bash
python main.py
```

### 4. Mở dashboard

Mở `dashboard/index.html` trong trình duyệt hoặc sử dụng server local:
```bash
cd dashboard
python -m http.server 8000
```
Sau đó truy cập http://localhost:8000

## Testing

Chạy unit tests:
```bash
cd simulator
python -m pytest tests/ -v
```

Chạy test cơ bản offline:
```bash
python test_phase1.py
```

## Cấu hình nâng cao

### Tham số chính trong config.py

- `TIME_SCALE`: Tỷ lệ thời gian (1 phút thực = X phút mô phỏng)
- `MOISTURE_LOW/HIGH`: Ngưỡng độ ẩm đất
- `PID_ENABLED`: Bật/tắt PID controller
- `RATE_LIMIT_MIN_INTERVAL`: Khoảng thời gian publish MQTT tối thiểu

### Feeds Adafruit IO

- `soil-moisture`: Độ ẩm đất (%)
- `temperature`: Nhiệt độ (°C)
- `light-intensity`: Ánh sáng (lux)
- `humidity`: Độ ẩm không khí (%)
- `co2-level`: Nồng độ CO2 (ppm)
- `pump-status`: Trạng thái bơm (ON/OFF)
- `pump-cmd`: Lệnh điều khiển bơm
- `ai-status`: Trạng thái AI
- `alert-status`: Cảnh báo

## Troubleshooting

### Lỗi kết nối MQTT
- Kiểm tra credentials trong `.env`
- Đảm bảo Adafruit IO account active
- Kiểm tra rate limit (30 points/min cho free tier)

### Simulator không khởi động
- Kiểm tra Python version >= 3.8
- Cài đặt lại dependencies: `pip install -r requirements.txt`
- Kiểm tra file `.env` tồn tại

### Dashboard không cập nhật
- Kiểm tra kết nối internet
- Xem console browser cho lỗi JavaScript
- Đảm bảo simulator đang chạy

## Phát triển thêm

### Thêm task mới
1. Tạo file trong `tasks/`
2. Implement class kế thừa từ base task
3. Đăng ký trong `main.py`

### Tùy chỉnh dashboard
- Sửa `dashboard/js/app.js` cho logic
- Sửa `dashboard/css/style.css` cho styling
- Sửa `dashboard/index.html` cho layout

## License

MIT License - Tự do sử dụng cho mục đích học tập và nghiên cứu.

> Lay key tai: https://io.adafruit.com → My Key

### 3. Chay simulator

```bash
python main.py
```

### 4. Mo dashboard

Mo file `dashboard/index.html` bang trinh duyet (Chrome/Firefox).
Dashboard tu dong ket noi MQTT qua WebSocket den Adafruit IO.

## Feeds MQTT (Adafruit IO)

| Feed name         | Huong | Mo ta                              |
|-------------------|-------|------------------------------------|
| soil-moisture     | PUB   | Do am dat (%)                      |
| temperature       | PUB   | Nhiet do khong khi (°C)            |
| light-intensity   | PUB   | Cuong do anh sang (lux)            |
| humidity          | PUB   | Do am khong khi (%)                |
| co2-level         | PUB   | Nong do CO2 (ppm)                  |
| pump-status       | PUB   | Trang thai bom (ON/OFF/OFFLINE)    |
| ai-status         | PUB   | Ket qua phan tich AI (JSON)        |
| watering-event    | PUB   | Su kien tuoi nuoc (JSON)           |
| pump-cmd          | SUB   | Lenh dieu khien bom (ON/OFF)       |
| greenhouse-mode   | SUB   | Che do hoat dong (AUTO/MANUAL)     |
| moisture-threshold| SUB   | Nguong do am mong muon (%)         |

## Cooperative Scheduler - Thu tu priority

| Task        | Priority | Interval | Mo ta                       |
|-------------|----------|----------|-----------------------------|
| MQTT        | 8 (cao)  | 15s      | Publish/subscribe MQTT      |
| Bom         | 7        | 3s       | Dieu khien bom (PID)        |
| CanhBao     | 6        | 5s       | Giam sat nguong, phat canh bao |
| MoiTruong   | 5        | 5s       | Mo phong cam bien           |
| AI          | 3        | 30s      | Phan tich tinh trang cay    |
| LuuTru      | 2 (thap) | 30s      | Luu SQLite                  |

## Yeu cau ky thuat

- Python 3.8+
- Adafruit IO free account (gioi han 30 data points/phut)
- Trinh duyet ho tro WebSocket (Chrome, Firefox, Edge)
