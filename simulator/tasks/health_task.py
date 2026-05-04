"""
Nha Kinh Thong Minh - Health Check Task
=============================================
Cung cap non-blocking HTTP endpoint de monitor tu ben ngoai (vd: Docker, Pingdom).
"""

import socket
import json
import logging

from tasks.base_task import BaseTask

logger = logging.getLogger("task.health")

class HealthCheckTask(BaseTask):
    def __init__(self, greenhouse, port=8080):
        self.greenhouse = greenhouse
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(5)
            self.server_socket.setblocking(False)
            logger.info(f"[OK] Health Check Server lang nghe tai cong {self.port}")
        except Exception as e:
            logger.error(f"[LOI] Khong the bind port {self.port}: {e}")
            self.server_socket = None

    def run(self):
        if not self.server_socket:
            return
            
        try:
            client, addr = self.server_socket.accept()
            client.settimeout(0.5)
            try:
                request = client.recv(1024)
                if b"GET /health" in request or b"GET / " in request:
                    stats = self.greenhouse.get_statistics()
                    sensors = self.greenhouse.get_sensors()
                    
                    # Kiem tra tinh trang MQTT (Neu task bi chet hoac disconnected)
                    mqtt_status = "offline"
                    # Thu tim MQTT task trong scheduler (Neu co reference)
                    # Hoac kiem tra thuoc tinh connected neu duoc gan tren greenhouse
                    # O day don gian tra ve status
                    
                    data = {
                        "status": "healthy",
                        "sim_time": self.greenhouse.get_sim_time_str(),
                        "sensors": {
                            "moisture": sensors.get("soil_moisture"),
                            "temperature": sensors.get("temperature"),
                            "light": sensors.get("light_intensity"),
                        },
                        "actuators": {
                            "pump_on": self.greenhouse.is_pump_on(),
                            "pump_duty": self.greenhouse.get_pump_duty()
                        },
                        "alerts_fired": stats.get("alerts_fired", 0),
                        "total_pump_cycles": stats.get("total_pump_cycles", 0)
                    }
                    
                    body = json.dumps(data, indent=2)
                    response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}"
                    client.sendall(response.encode('utf-8'))
            except Exception as e:
                pass
            finally:
                client.close()
        except BlockingIOError:
            # Khong co connection moi
            pass
        except Exception as e:
            logger.error(f"[LOI] HealthCheck: {e}")

    def shutdown(self):
        if self.server_socket:
            self.server_socket.close()
            logger.info("[OK] Da dong Health Check Server")
