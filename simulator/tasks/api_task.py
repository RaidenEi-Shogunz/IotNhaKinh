"""
Nha Kinh Thong Minh - REST API + WebSocket Server Task
========================================================
Nang cap v4.0: Them local API de dashboard hoat dong offline hoan toan.

Kien truc:
  - FastAPI chay tren uvicorn background thread (khong block Scheduler)
  - WebSocket /ws/realtime: push snapshot moi 2 giay den tat ca clients
  - GET /api/sensors       : lay snapshot hien tai
  - GET /api/history       : query SQLite sensor_data co filter
  - GET /api/stats         : thong ke phien lam viec
  - GET /api/alerts        : canh bao gan nhat
  - GET /api/watering-log  : nhat ky tuoi nuoc
  - POST /api/control/pump : bat/tat bom (MANUAL mode)
  - POST /api/control/mode : chuyen AUTO/MANUAL
  - POST /api/control/threshold : cap nhat nguong do am
  - GET /health            : health check (gia nguyen cho Docker)

Uu diem so voi HealthCheckTask cu:
  - Thay the hoan toan HealthCheckTask (socket thu cong) bang FastAPI
  - Dashboard khong can Adafruit IO key de hoat dong
  - Latency ~10ms thay vi ~500ms qua Adafruit IO
  - CORS da cau hinh cho phep dashboard HTML file:// truy cap
  - WebSocket push real-time thay vi dashboard phai poll
  - Query SQLite lich su voi paging va filter thoi gian
"""

import json
import time
import sqlite3
import logging
import threading
from typing import Any, Dict, List, Optional, Set

from tasks.base_task import BaseTask

logger = logging.getLogger("task.api")

try:
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import JSONResponse, FileResponse
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    logger.warning(
        "[API] fastapi / uvicorn chua duoc cai dat. "
        "Chay: pip install fastapi uvicorn[standard] "
        "de kich hoat REST API + WebSocket."
    )


# ---------------------------------------------------------------------------
# Pydantic request models (chi dung khi FastAPI available)
# ---------------------------------------------------------------------------
if _FASTAPI_AVAILABLE:
    class PumpCommand(BaseModel):
        state: str   # "ON" | "OFF"

    class ModeCommand(BaseModel):
        mode: str    # "AUTO" | "MANUAL"

    class ThresholdCommand(BaseModel):
        value: float  # 10.0 - 80.0


# ---------------------------------------------------------------------------
# WebSocket Connection Manager
# ---------------------------------------------------------------------------
class WSConnectionManager:
    """Quan ly tap hop cac WebSocket clients dang ket noi (thread-safe)."""

    def __init__(self):
        self._lock: threading.Lock = threading.Lock()
        self._clients: Set[Any] = set()

    def add(self, ws: Any) -> None:
        with self._lock:
            self._clients.add(ws)

    def remove(self, ws: Any) -> None:
        with self._lock:
            self._clients.discard(ws)

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    async def broadcast(self, data: dict) -> None:
        """Gui JSON den tat ca clients. Loai bo client bi disconnect."""
        payload = json.dumps(data, ensure_ascii=False)
        dead: list = []
        with self._lock:
            clients_snapshot = list(self._clients)
        for ws in clients_snapshot:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)


# ---------------------------------------------------------------------------
# Main Task
# ---------------------------------------------------------------------------
class APIServerTask(BaseTask):
    """
    Task khoi dong FastAPI + uvicorn tren background thread.
    Cooperative Scheduler chi goi run() de push WebSocket broadcast dinh ky.
    """

    def __init__(self, greenhouse: Any, config: Any, db_path: Optional[str] = None):
        self.greenhouse = greenhouse
        self.config     = config
        self.db_path    = db_path or getattr(config, "DB_PATH", "dulieu_nhakinh.db")
        self.port       = getattr(config, "API_PORT", 8080)
        self.ws_manager = WSConnectionManager()
        self._server_thread: Optional[threading.Thread] = None
        self._uvicorn_server: Optional[Any] = None
        self._last_broadcast: float = 0.0
        self._broadcast_interval: float = getattr(config, "WS_BROADCAST_INTERVAL", 2.0)
        self._started: bool = False
        self._event_loop: Optional[Any] = None  # FIX: Luu event loop cua uvicorn thread

        if _FASTAPI_AVAILABLE:
            self._app = self._build_app()
            self._start_server()
        else:
            self._app = None

    # ------------------------------------------------------------------
    # FastAPI app builder
    # ------------------------------------------------------------------
    def _build_app(self) -> Any:
        app = FastAPI(
            title="Nha Kinh Thong Minh API",
            description="REST API + WebSocket cho he thong IoT nha kinh",
            version="4.0.0",
        )

        # FIX: Capture event loop khi uvicorn khoi dong xong
        # Dung on_event("startup") de lay loop tu ben trong async context
        @app.on_event("startup")
        async def _capture_loop():
            import asyncio
            self._event_loop = asyncio.get_running_loop()
            logger.info("[WS] Da capture event loop cho broadcast real-time")

        # CORS: cho phep dashboard HTML (file://) va localhost dev server
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Trong prod nen gioi han cu the
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

        gh  = self.greenhouse
        cfg = self.config
        mgr = self.ws_manager
        
        # Moved dashboard mount to bottom

        # ---- GET /health ------------------------------------------------
        @app.get("/health")
        async def health():
            stats   = gh.get_statistics()
            sensors = gh.get_sensors()
            return {
                "status":            "healthy",
                "sim_time":          gh.get_sim_time_str(),
                "sim_day":           gh.get_sim_day(),
                "ws_clients":        mgr.count(),
                "sensors":           sensors,
                "pump_on":           gh.is_pump_on(),
                "pump_duty":         gh.get_pump_duty(),
                "mode":              gh.get_mode(),
                "alerts_fired":      stats.get("alerts_fired", 0),
                "total_pump_cycles": stats.get("total_pump_cycles", 0),
            }

        # ---- GET /api/sensors -------------------------------------------
        @app.get("/api/sensors")
        async def get_sensors():
            """Lay snapshot du lieu hien tai cua tat ca cam bien + trang thai he thong."""
            sensors = gh.get_sensors()
            pid     = gh.get_pid_state()
            weather = gh.get_weather()
            ai      = gh.get_ai_status()
            stats   = gh.get_statistics()
            crop    = gh.get_crop_state()
            predictions = getattr(gh, "prediction_points", [])
            return {
                "timestamp":   time.time(),
                "sim_time":    gh.get_sim_time_str(),
                "sim_day":     gh.get_sim_day(),
                "sensors":     sensors,
                "pump": {
                    "on":           gh.is_pump_on(),
                    "duty":         gh.get_pump_duty(),
                    "mode":         gh.get_mode(),
                    "threshold":    gh.get_threshold(),
                    "total_cycles": stats.get("total_pump_cycles", 0),
                    "total_water":  stats.get("total_water_used", 0),
                },
                "pid":     pid,
                "weather": weather,
                "ai":      ai,
                "crop":    crop,
                "predictions": predictions,
            }

        # ---- POST /api/gemini -------------------------------------------
        @app.post("/api/gemini")
        async def proxy_gemini(request: Request):
            """Proxy goi API Gemini Vision tranh loi CORS tu trinh duyet."""
            try:
                data = await request.json()
                api_key = data.get("api_key")
                image_base64 = data.get("image")
                prompt = data.get("prompt", "Phân tích chi tiết tình trạng cây trồng trong ảnh này và đưa ra khuyến nghị chăm sóc.")
                
                if not api_key or not image_base64:
                    raise HTTPException(status_code=400, detail="Thiếu api_key hoặc image base64")
                    
                # Xóa Data URI prefix nếu có
                if "," in image_base64:
                    image_base64 = image_base64.split(",")[1]

                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
                headers = {
                    "content-type": "application/json"
                }
                
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": prompt
                                },
                                {
                                    "inline_data": {
                                        "mime_type": "image/jpeg",
                                        "data": image_base64
                                    }
                                }
                            ]
                        }
                    ],
                    "generationConfig": {
                        "response_mime_type": "application/json"
                    }
                }
                
                import urllib.request
                import json
                import urllib.error
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
                
                with urllib.request.urlopen(req, timeout=20) as response:
                    res_body = response.read().decode('utf-8')
                    return json.loads(res_body)
                    
            except urllib.error.HTTPError as e:
                err_msg = e.read().decode('utf-8')
                logger.error(f"[Gemini Proxy] HTTP Error: {err_msg}")
                raise HTTPException(status_code=e.code, detail=f"Gemini API Error: {err_msg}")
            except Exception as e:
                logger.error(f"[Gemini Proxy] Error: {e}")
                raise HTTPException(status_code=500, detail=f"Proxy Error: {str(e)}")


        # ---- GET /api/history -------------------------------------------
        @app.get("/api/history")
        async def get_history(
            field:      str   = Query("soil_moisture", description="Ten cot: soil_moisture | temperature | light_intensity | humidity | co2_level"),
            limit:      int   = Query(100, ge=1, le=2000, description="So ban ghi toi da"),
            from_ts:    Optional[float] = Query(None,  alias="from", description="Unix timestamp bat dau"),
            to_ts:      Optional[float] = Query(None,  alias="to",   description="Unix timestamp ket thuc"),
            sim_day:    Optional[int]   = Query(None,  description="Loc theo ngay mo phong"),
            aggregate:  Optional[str]   = Query(None,  description="Nhom theo: minute | hour | day"),
        ):
            """
            Query SQLite sensor_data voi filter linh hoat.
            Tra ve danh sach {timestamp, sim_time, value} de ve bieu do.
            """
            # Whitelist cac cot hop le
            VALID_FIELDS = {
                "soil_moisture", "temperature", "light_intensity",
                "humidity", "co2_level", "pump_on", "pump_duty",
            }
            if field not in VALID_FIELDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"field '{field}' khong hop le. Dung: {sorted(VALID_FIELDS)}"
                )

            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row

                if aggregate in ("minute", "hour", "day"):
                    # Aggregate: lay trung binh theo khoang thoi gian
                    if aggregate == "minute":
                        group_expr = "CAST(timestamp / 60 AS INTEGER)"
                        label_expr = "strftime('%H:%M', datetime(timestamp, 'unixepoch', 'localtime'))"
                    elif aggregate == "hour":
                        group_expr = "CAST(timestamp / 3600 AS INTEGER)"
                        label_expr = "strftime('%d/%m %H:00', datetime(timestamp, 'unixepoch', 'localtime'))"
                    else:  # day
                        group_expr = "sim_day"
                        label_expr = "'Ngay ' || sim_day"

                    query = f"""
                        SELECT
                            AVG(timestamp)   AS timestamp,
                            {label_expr}     AS sim_time,
                            AVG({field})     AS value,
                            COUNT(*)         AS count
                        FROM sensor_data
                        WHERE 1=1
                        {' AND timestamp >= ?' if from_ts else ''}
                        {' AND timestamp <= ?' if to_ts   else ''}
                        {' AND sim_day = ?'    if sim_day else ''}
                        GROUP BY {group_expr}
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """
                else:
                    query = f"""
                        SELECT timestamp, sim_time, {field} AS value
                        FROM sensor_data
                        WHERE 1=1
                        {' AND timestamp >= ?' if from_ts else ''}
                        {' AND timestamp <= ?' if to_ts   else ''}
                        {' AND sim_day = ?'    if sim_day else ''}
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """

                params: list = []
                if from_ts: params.append(from_ts)
                if to_ts:   params.append(to_ts)
                if sim_day: params.append(sim_day)
                params.append(limit)

                rows = conn.execute(query, params).fetchall()
                conn.close()

                data = [
                    {
                        "timestamp": row["timestamp"],
                        "sim_time":  row["sim_time"],
                        "value":     round(row["value"], 2) if row["value"] is not None else None,
                    }
                    for row in reversed(rows)  # Tra ve theo thu tu thoi gian tang dan
                ]
                return {"field": field, "count": len(data), "data": data}

            except sqlite3.Error as e:
                logger.error(f"[API] SQLite error in /api/history: {e}")
                raise HTTPException(status_code=500, detail=f"Database error: {e}")

        # ---- GET /api/stats ---------------------------------------------
        @app.get("/api/stats")
        async def get_stats():
            """Thong ke toan bo phien lam viec."""
            return gh.get_statistics()

        # ---- GET /api/alerts -------------------------------------------
        @app.get("/api/alerts")
        async def get_alerts(count: int = Query(20, ge=1, le=200)):
            """Lay canh bao gan nhat."""
            return {"alerts": gh.get_recent_alerts(count=count)}

        # ---- GET /api/watering-log ------------------------------------
        @app.get("/api/watering-log")
        async def get_watering_log(count: int = Query(30, ge=1, le=200)):
            """Lay nhat ky tuoi nuoc gan nhat."""
            return {"log": gh.get_watering_log(count=count)}

        # ---- POST /api/control/pump ------------------------------------
        @app.post("/api/control/pump")
        async def control_pump(cmd: "PumpCommand"):
            state = cmd.state.upper()
            if state not in ("ON", "OFF"):
                raise HTTPException(status_code=400, detail="state phai la ON hoac OFF")
            if gh.get_mode() == "AUTO":
                raise HTTPException(
                    status_code=409,
                    detail="He thong dang o che do AUTO. Chuyen sang MANUAL truoc."
                )
            gh.set_pump(state == "ON", trigger="API_MANUAL")
            logger.info(f"[API] Lenh bom: {state}")
            return {"ok": True, "pump_on": state == "ON"}

        # ---- POST /api/control/mode ------------------------------------
        @app.post("/api/control/mode")
        async def control_mode(cmd: "ModeCommand"):
            mode = cmd.mode.upper()
            if mode not in ("AUTO", "MANUAL"):
                raise HTTPException(status_code=400, detail="mode phai la AUTO hoac MANUAL")
            gh.set_mode(mode)
            logger.info(f"[API] Chuyen che do: {mode}")
            return {"ok": True, "mode": mode}

        # ---- POST /api/control/threshold ------------------------------
        @app.post("/api/control/threshold")
        async def control_threshold(cmd: "ThresholdCommand"):
            if not (10.0 <= cmd.value <= 80.0):
                raise HTTPException(
                    status_code=400,
                    detail=f"value phai trong [10, 80], nhan duoc {cmd.value}"
                )
            gh.set_threshold(cmd.value)
            gh.set_pid_setpoint(cmd.value)
            actual = gh.get_threshold()
            logger.info(f"[API] Nguong moi: {actual}%")
            return {"ok": True, "threshold": actual}

        # ---- WebSocket /ws/realtime ------------------------------------
        @app.websocket("/ws/realtime")
        async def ws_realtime(websocket: WebSocket):
            await websocket.accept()
            mgr.add(websocket)
            logger.info(f"[WS] Client moi ket noi. Tong: {mgr.count()}")
            try:
                # Gui ngay snapshot hien tai khi client vua ket noi
                snapshot = self._build_ws_payload()
                await websocket.send_text(json.dumps(snapshot, ensure_ascii=False))
                # Giu ket noi song — cho den khi client ngat
                while True:
                    try:
                        # Receive ping/pong de giu ket noi; timeout ngan tranh block
                        await websocket.receive_text()
                    except Exception:
                        break
            except WebSocketDisconnect:
                pass
            finally:
                mgr.remove(websocket)
                logger.info(f"[WS] Client ngat ket noi. Con lai: {mgr.count()}")

        # FIX: Phuc vu truc tiep giao dien Dashboard qua FastAPI de khong can dung Live Server
        # Luon de mount("/") o cuoi cung de khong che khuat cac route API khac!
        import os
        dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "dashboard")
        if os.path.exists(dashboard_dir):
            @app.get("/")
            async def serve_dashboard_index():
                return FileResponse(os.path.join(dashboard_dir, "index.html"))
            app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

        return app

    def _build_ws_payload(self) -> dict:
        """Xay dung payload WebSocket tu greenhouse state hien tai."""
        gh      = self.greenhouse
        sensors = gh.get_sensors()
        pid     = gh.get_pid_state()
        weather = gh.get_weather()
        ai      = gh.get_ai_status()
        stats   = gh.get_statistics()
        crop    = gh.get_crop_state()
        predictions = getattr(gh, "prediction_points", [])
        return {
            "type":      "snapshot",
            "timestamp": time.time(),
            "sim_time":  gh.get_sim_time_str(),
            "sim_day":   gh.get_sim_day(),
            "sensors":   sensors,
            "pump": {
                "on":           gh.is_pump_on(),
                "duty":         gh.get_pump_duty(),
                "mode":         gh.get_mode(),
                "threshold":    gh.get_threshold(),
                "total_cycles": stats.get("total_pump_cycles", 0),
                "total_water":  stats.get("total_water_used", 0),
            },
            "pid":     pid,
            "weather": weather,
            "ai":      ai,
            "crop":    crop,
            "predictions": predictions,
            "recent_alerts": gh.get_recent_alerts(count=5),
        }

    # ------------------------------------------------------------------
    # uvicorn background thread
    # ------------------------------------------------------------------
    def _start_server(self) -> None:
        if not _FASTAPI_AVAILABLE:
            return
        try:
            uv_config = uvicorn.Config(
                app=self._app,
                host="0.0.0.0",
                port=self.port,
                log_level="warning",   # Im logging cua uvicorn, dung logger cua minh
                access_log=False,
            )
            self._uvicorn_server = uvicorn.Server(uv_config)

            self._server_thread = threading.Thread(
                target=self._uvicorn_server.run,
                name="APIServer",
                daemon=True,   # Tu dong chet khi main thread thoat
            )
            self._server_thread.start()
            self._started = True
            logger.info(f"[OK] API Server khoi dong tai http://0.0.0.0:{self.port}")
            logger.info(f"     REST: http://localhost:{self.port}/api/sensors")
            logger.info(f"     WS  : ws://localhost:{self.port}/ws/realtime")
            logger.info(f"     Docs: http://localhost:{self.port}/docs")
        except Exception as e:
            logger.error(f"[LOI] Khong the khoi dong API Server: {e}")

    # ------------------------------------------------------------------
    # BaseTask interface
    # ------------------------------------------------------------------
    def run(self) -> None:
        """
        Duoc goi moi WS_BROADCAST_INTERVAL giay boi Cooperative Scheduler.
        Broadcast snapshot den tat ca WebSocket clients.
        Non-blocking: dung asyncio.run_coroutine_threadsafe trong event loop cua uvicorn.
        """
        if not _FASTAPI_AVAILABLE or not self._started:
            return
        if self.ws_manager.count() == 0:
            return

        now = time.time()
        if (now - self._last_broadcast) < self._broadcast_interval:
            return
        self._last_broadcast = now

        # FIX: Dung event loop da capture tu startup event thay vi config.loop (khong ton tai)
        try:
            import asyncio
            loop = self._event_loop
            if loop and loop.is_running():
                payload = self._build_ws_payload()
                asyncio.run_coroutine_threadsafe(
                    self.ws_manager.broadcast(payload),
                    loop,
                )
        except Exception as e:
            logger.debug(f"[WS] Broadcast skip: {e}")

    def shutdown(self) -> None:
        """Dung uvicorn server khi he thong tat."""
        if self._uvicorn_server:
            try:
                self._uvicorn_server.should_exit = True
                logger.info("[OK] Da dung API Server")
            except Exception:
                pass
