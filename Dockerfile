# Dockerfile cho simulator
FROM python:3.11-slim

# Cài đặt system dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy requirements và cài đặt Python packages
COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY simulator/ .

# Tạo thư mục cho database
RUN mkdir -p /app/data

# Expose port nếu cần (cho tương lai)
# EXPOSE 8000

# Command để chạy
CMD ["python", "main.py"]