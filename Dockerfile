FROM python:3.10-slim

WORKDIR /app

# Copy requirement and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy simulator source code
COPY simulator/ ./simulator/
# Copy dashboard static files
COPY dashboard/ ./dashboard/

# Expose API/Web port
EXPOSE 8080

# Command to run the system
CMD ["python", "simulator/main.py"]