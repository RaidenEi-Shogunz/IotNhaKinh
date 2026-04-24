/**
 * localApiService.js - Nang cap v4.0
 * =====================================
 * Quan ly ket noi den Local REST API + WebSocket server (APIServerTask).
 *
 * Chien luoc dual-source:
 *   1. Thu ket noi Local WS (ws://localhost:8080/ws/realtime)
 *   2. Neu co ket noi local: du lieu den tu WS push (latency ~10ms)
 *   3. Neu khong co local:   fallback sang Adafruit IO MQTT nhu cu
 *
 * Tat ca xu ly UI (updateGauge, addAlert...) dung chung ham voi mqttService.js
 * nen 2 nguon hoan toan co the song song hoac thay the nhau.
 */

import { state, CONFIG } from './config.js';
import {
    updateConnectionStatus, updateGauge, updatePumpDisplay,
    updateModeDisplay, updatePIDDisplay, updateAIDisplay,
    addWateringLogFromEvent, addAlert, syncSimClock
} from './uiController.js';
import { addHistory, loadBulkHistory, addPumpAnnotation } from './chartManager.js';

// Base URL cho Local API (co the override bang URL params)
const _params      = new URLSearchParams(window.location.search);
const LOCAL_HOST   = _params.get('api_host') || 'localhost';
const LOCAL_PORT   = _params.get('api_port') || '8080';
export const LOCAL_API_BASE = `http://${LOCAL_HOST}:${LOCAL_PORT}`;
export const LOCAL_WS_URL   = `ws://${LOCAL_HOST}:${LOCAL_PORT}/ws/realtime`;

let _ws               = null;
let _wsReconnectTimer = null;
let _wsConnected      = false;
let _historyLoaded    = false;

// Tra ve true neu dang ket noi voi local server
export function isLocalConnected() {
    return _wsConnected;
}

// ------------------------------------------------------------------
// Kiem tra local server co dang chay khong (non-blocking)
// ------------------------------------------------------------------
export async function checkLocalServer() {
    try {
        const res = await fetch(`${LOCAL_API_BASE}/health`, {
            signal: AbortSignal.timeout(2000),  // 2 giay timeout
        });
        return res.ok;
    } catch {
        return false;
    }
}

// ------------------------------------------------------------------
// Ket noi WebSocket den local server
// ------------------------------------------------------------------
export function connectLocalWS(onConnected, onDisconnected) {
    if (_ws && _ws.readyState === WebSocket.OPEN) return;

    console.log(`[LocalAPI] Thu ket noi WS: ${LOCAL_WS_URL}`);
    _ws = new WebSocket(LOCAL_WS_URL);

    _ws.onopen = () => {
        _wsConnected = true;
        clearTimeout(_wsReconnectTimer);
        console.log('[LocalAPI] WebSocket da ket noi!');
        updateLocalStatusBadge(true);
        if (onConnected) onConnected();

        // Load lich su qua REST API (1 lan duy nhat sau khi ket noi)
        if (!_historyLoaded) {
            loadHistoryFromLocal().then(() => { _historyLoaded = true; });
        }
    };

    _ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'snapshot') {
                _applySnapshot(data);
            }
        } catch (e) {
            console.warn('[LocalAPI] Loi parse WS message:', e);
        }
    };

    _ws.onclose = () => {
        _wsConnected = false;
        updateLocalStatusBadge(false);
        console.log('[LocalAPI] WebSocket ngat ket noi. Thu lai sau 5s...');
        if (onDisconnected) onDisconnected();
        // Auto-reconnect sau 5 giay
        _wsReconnectTimer = setTimeout(() => {
            connectLocalWS(onConnected, onDisconnected);
        }, 5000);
    };

    _ws.onerror = () => {
        // onerror luon duoc goi truoc onclose, khong can log them
        _wsConnected = false;
    };
}

export function disconnectLocalWS() {
    clearTimeout(_wsReconnectTimer);
    if (_ws) { _ws.close(); _ws = null; }
}

// ------------------------------------------------------------------
// Apply snapshot nhan duoc tu WebSocket vao UI
// ------------------------------------------------------------------
function _applySnapshot(data) {
    const s = data.sensors || {};

    // Cam bien
    if (s.soil_moisture   != null) { updateGauge('moisture',    s.soil_moisture);   addHistory('moisture',    s.soil_moisture,    data.sim_time); }
    if (s.temperature     != null) { updateGauge('temperature', s.temperature);     addHistory('temperature', s.temperature,     data.sim_time); }
    if (s.light_intensity != null) { updateGauge('light',       s.light_intensity); addHistory('light',       s.light_intensity, data.sim_time); }
    if (s.humidity        != null) { updateGauge('humidity',    s.humidity);        addHistory('humidity',    s.humidity,        data.sim_time); }
    if (s.co2_level       != null) { updateGauge('co2',         s.co2_level);       addHistory('co2',         s.co2_level,       data.sim_time); }

    // Bom
    if (data.pump) {
        const pump = data.pump;
        if (pump.on != null) {
            if (state.pumpOn !== pump.on) addPumpAnnotation(pump.on ? 'ON' : 'OFF', data.sim_time || '');
            state.pumpOn = pump.on;
            updatePumpDisplay(pump.on);
        }
        if (pump.mode) { state.currentMode = pump.mode; updateModeDisplay(); }
    }

    // PID
    if (data.pid) {
        updatePIDDisplay(data.pid.output, data.pid.setpoint);
    }

    // AI
    if (data.ai) {
        updateAIDisplay(data.ai);
    }

    // Dong ho + thoi tiet
    if (data.sim_time) {
        syncSimClock(data.sim_time, data.weather?.condition);
        const dayEl = document.getElementById('sim-day');
        if (dayEl && data.sim_day != null) dayEl.textContent = `Ngày ${data.sim_day}`;
    }

    // Canh bao moi
    if (Array.isArray(data.recent_alerts)) {
        _syncAlerts(data.recent_alerts);
    }
}

// Track alert da hien thi de khong hien trung
const _shownAlerts = new Set();

function _syncAlerts(alerts) {
    alerts.forEach(a => {
        const key = `${a.real_time}_${a.type}`;
        if (!_shownAlerts.has(key)) {
            _shownAlerts.add(key);
            addAlert(a.severity || 'INFO', a.message, a.sim_time || a.real_time);
        }
    });
    // Giu Set nho gon
    if (_shownAlerts.size > 200) {
        const arr = [..._shownAlerts];
        arr.splice(0, 100).forEach(k => _shownAlerts.delete(k));
    }
}

// ------------------------------------------------------------------
// Load lich su tu REST API /api/history
// ------------------------------------------------------------------
export async function loadHistoryFromLocal(limit = 80) {
    const sensors = ['soil_moisture', 'temperature', 'light_intensity', 'humidity', 'co2_level'];
    const keyMap  = {
        'soil_moisture':   'moisture',
        'temperature':     'temperature',
        'light_intensity': 'light',
        'humidity':        'humidity',
        'co2_level':       'co2',
    };

    console.log('[LocalAPI] Dang load lich su tu SQLite qua REST API...');

    const promises = sensors.map(async (field) => {
        try {
            const res  = await fetch(`${LOCAL_API_BASE}/api/history?field=${field}&limit=${limit}`);
            if (!res.ok) return null;
            const json = await res.json();
            return { field, data: json.data || [] };
        } catch {
            return null;
        }
    });

    const results = await Promise.all(promises);
    let loaded = 0;

    for (const r of results) {
        if (!r || r.data.length === 0) continue;
        const chartKey   = keyMap[r.field];
        const parsedData = r.data.map(p => ({
            value: p.value,
            time:  p.sim_time || new Date(p.timestamp * 1000).toLocaleTimeString('vi-VN'),
        })).filter(p => p.value != null && !isNaN(p.value));

        if (parsedData.length > 0) {
            loadBulkHistory(chartKey, parsedData);
            updateGauge(chartKey, parsedData[parsedData.length - 1].value);
            loaded++;
        }
    }
    console.log(`[LocalAPI] Da load lich su ${loaded}/${sensors.length} sensors tu SQLite.`);
}

// ------------------------------------------------------------------
// GUI: Badge trang thai Local API tren header
// ------------------------------------------------------------------
function updateLocalStatusBadge(connected) {
    let badge = document.getElementById('local-api-status');
    if (!badge) return;
    if (connected) {
        badge.className = 'local-badge online';
        badge.title     = `Local API: ${LOCAL_API_BASE}`;
        badge.textContent = '⚡ Local';
    } else {
        badge.className = 'local-badge offline';
        badge.title     = 'Local API: mat ket noi';
        badge.textContent = '⚡ Local (off)';
    }
}

// ------------------------------------------------------------------
// Publish lenh dieu khien den local API (song song voi MQTT)
// ------------------------------------------------------------------
export async function sendLocalCommand(endpoint, body) {
    try {
        const res = await fetch(`${LOCAL_API_BASE}${endpoint}`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(body),
            signal:  AbortSignal.timeout(3000),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            console.warn(`[LocalAPI] Lenh ${endpoint} loi:`, err.detail || res.status);
            return { ok: false, error: err.detail };
        }
        return await res.json();
    } catch (e) {
        console.warn(`[LocalAPI] Lenh ${endpoint} that bai:`, e.message);
        return { ok: false, error: e.message };
    }
}
