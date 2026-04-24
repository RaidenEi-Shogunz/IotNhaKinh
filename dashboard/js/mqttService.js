import { CONFIG, state } from './config.js';
import {
    updateConnectionStatus, updateGauge, updatePumpDisplay,
    updateModeDisplay, updatePIDDisplay, updateAIDisplay,
    addWateringLogFromEvent, addAlert, syncSimClock
} from './uiController.js';
import { addHistory, loadBulkHistory, addPumpAnnotation } from './chartManager.js';
import { escapeHtml } from './utils.js';

let client = null;
let historyLoaded = false; // FIX Bug An 11: Flag chong Race condition giua MQTT message va REST API history

export function connectMQTT() {
    if (!CONFIG.username || !CONFIG.key) return false;

    const options = {
        username:        CONFIG.username,
        password:        CONFIG.key,
        clientId:        'dashboard_' + Math.random().toString(16).substring(2, 10),
        reconnectPeriod: 5000,   // 5s lan dau
        connectTimeout:  15000,
        keepalive:       60,
        clean:           true,
        protocolVersion: 4,      // MQTTv3.1.1 qua WebSocket (tuong thich Adafruit IO WSS)
    };

    client = mqtt.connect(CONFIG.mqttUrl, options);

    // Exponential backoff cho reconnect (1s -> 120s)
    let _reconnectDelay = 5000;
    client.on('reconnect', () => {
        updateConnectionStatus('reconnecting');
        _reconnectDelay = Math.min(_reconnectDelay * 2, 120000);
        client.options.reconnectPeriod = _reconnectDelay;
        console.log(`[MQTT] Dang ket noi lai... (delay=${_reconnectDelay}ms)`);
    });

    client.on('connect', () => {
        state.connected = true;
        _reconnectDelay = 5000;           // Reset sau khi thanh cong
        client.options.reconnectPeriod = _reconnectDelay;
        updateConnectionStatus('online');
        console.log('[MQTT] Da ket noi!');

        Object.values(CONFIG.feeds).forEach(feed => {
            const topic = `${CONFIG.username}/feeds/${feed}`;
            client.subscribe(topic, { qos: 1 });
        });

        // Load lich su bang Promise.all (song song, khong tuan tu)
        fetchHistoricalDataParallel();
    });

    client.on('message', (topic, message) => {
        const payload = message.toString().trim();
        const feed    = topic.split('/feeds/')[1];
        
        // FIX Bug An 11: Race condition - Bo qua message real-time cua sensor neu lich su chua load xong.
        // Ngan chan viec updateChart bi goi xen ngang, gay lap du lieu hoac sai thu tu thoi gian.
        if (!historyLoaded) {
            // v5.0: sensorData la batch feed chinh; cac feed sensor rieng giu lai de backward compat
            const isSensorFeed = feed === f.sensorData ||
                (Object.values(CONFIG.feeds).includes(feed) &&
                 ['moisture', 'temperature', 'light', 'humidity', 'co2'].some(s => CONFIG.feeds[s] === feed));
            if (isSensorFeed) {
                console.log(`[MQTT] Bo qua message cua ${feed} do lich su chua load xong (chong Race Condition)`);
                return;
            }
        }
        
        state.msgCount++;
        const counterEl = document.getElementById('msg-counter');
        if (counterEl) counterEl.textContent = `${state.msgCount} tin nhan`;
        handleMessage(feed, payload);
    });

    client.on('offline', () => {
        state.connected = false;
        updateConnectionStatus('offline');
    });

    client.on('error', (err) => {
        console.error('[MQTT] Loi:', err.message || err);
        state.connected = false;
        updateConnectionStatus('offline');
        
        // Chống Ban IP: Ngừng auto-reconnect nếu sai mật khẩu/tài khoản
        if (err.message && (err.message.includes('authorized') || err.message.includes('Bad username'))) {
            alert('Sai Username hoặc Key Adafruit IO! Kết nối đã bị chặn để tránh bị Ban IP. Vui lòng F5 và nhập lại.');
            client.end(); 
        }
    });

    return true;
}

function handleMessage(feed, payload) {
    const f         = CONFIG.feeds;
    const timestamp = new Date().toLocaleTimeString('vi-VN');

    if (feed === f.sensorData) {
        // NANG CAP v5.0: Batch feed - giai ma 1 JSON thay vi 6 feeds rieng
        try {
            const d = JSON.parse(payload);
            if (typeof d !== 'object' || d === null) throw new Error('Invalid sensor-data payload');
            if (d.soil_moisture  != null) { const v = parseFloat(d.soil_moisture);  if (!isNaN(v)) { updateGauge('moisture',    v); addHistory('moisture',    v, timestamp); } }
            if (d.temperature    != null) { const v = parseFloat(d.temperature);    if (!isNaN(v)) { updateGauge('temperature', v); addHistory('temperature', v, timestamp); } }
            if (d.light_intensity != null){ const v = parseFloat(d.light_intensity); if (!isNaN(v)) { updateGauge('light',       v); addHistory('light',       v, timestamp); } }
            if (d.humidity       != null) { const v = parseFloat(d.humidity);       if (!isNaN(v)) { updateGauge('humidity',    v); addHistory('humidity',    v, timestamp); } }
            if (d.co2_level      != null) { const v = parseFloat(d.co2_level);      if (!isNaN(v)) { updateGauge('co2',         v); addHistory('co2',         v, timestamp); } }
            if (d.ec_level       != null) { const v = parseFloat(d.ec_level);       if (!isNaN(v)) { updateGauge('ec',          v); addHistory('ec',          v, timestamp); } }
            if (d.ph_level       != null) { const v = parseFloat(d.ph_level);       if (!isNaN(v)) { updateGauge('ph',          v); addHistory('ph',          v, timestamp); } }
            if (d.pump_status    != null) {
                const on = d.pump_status.toUpperCase() === 'ON';
                if (state.pumpOn !== on) addPumpAnnotation(on ? 'ON' : 'OFF', timestamp);
                state.pumpOn = on;
                updatePumpDisplay(on);
            }
        } catch (e) {
            console.warn('[MQTT] Loi parse sensor-data:', e);
        }
    } else if (feed === f.moisture) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('moisture', v); addHistory('moisture', v, timestamp); }
    } else if (feed === f.temperature) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('temperature', v); addHistory('temperature', v, timestamp); }
    } else if (feed === f.light) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('light', v); addHistory('light', v, timestamp); }
    } else if (feed === f.humidity) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('humidity', v); addHistory('humidity', v, timestamp); }
    } else if (feed === f.co2) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('co2', v); addHistory('co2', v, timestamp); }
    } else if (feed === f.pumpStatus) {
        const on = payload.toUpperCase() === 'ON';
        if (state.pumpOn !== on) addPumpAnnotation(on ? 'ON' : 'OFF', timestamp);
        state.pumpOn = on;
        updatePumpDisplay(on);
    } else if (feed === f.mode) {
        state.currentMode = payload.toUpperCase();
        updateModeDisplay();
    } else if (feed === f.aiStatus) {
        try {
            const ai = JSON.parse(payload);
            if (typeof ai !== 'object' || ai === null) throw new Error('Invalid AI payload');
            updateAIDisplay(ai);
            if (ai.pid_output != null && ai.pid_setpoint != null) {
                updatePIDDisplay(ai.pid_output, ai.pid_setpoint);
            }
            if (ai.sim_time) syncSimClock(ai.sim_time, ai.weather_condition);
            if (ai.sim_day != null) {
                const dayEl = document.getElementById('sim-day');
                if (dayEl) dayEl.textContent = `Ngày ${ai.sim_day}`;
            }
        } catch (e) {
            updateAIDisplay({ status: payload, confidence: 0, recommendation: '' });
        }
    } else if (feed === f.wateringEvent) {
        try {
            const event = JSON.parse(payload);
            if (typeof event !== 'object' || event === null || !event.action) {
                throw new Error('Invalid watering event payload');
            }
            addWateringLogFromEvent(event);
            const on = event.action === 'ON';
            addPumpAnnotation(on ? 'ON' : 'OFF', timestamp);
            state.pumpOn = on;
            updatePumpDisplay(on);
        } catch (e) {
            console.warn('[MQTT] Loi parse watering-event:', e);
        }
    } else if (feed === f.alertStatus) {
        try {
            const alert = JSON.parse(payload);
            if (typeof alert !== 'object' || alert === null) throw new Error('Invalid alert payload');
            addAlert(
                alert.severity || 'WARNING',
                alert.message  || payload,
                alert.sim_time || new Date().toLocaleTimeString('vi-VN'),
            );
        } catch (e) {
            addAlert('INFO', escapeHtml(payload), new Date().toLocaleTimeString('vi-VN'));
        }
    }
}

export function publishMQTT(feed, value) {
    if (!client || !state.connected) return;
    const topic = `${CONFIG.username}/feeds/${feed}`;
    client.publish(topic, String(value), { qos: 1 });
    console.log(`[GUI] ${topic} = ${value}`);
}

/**
 * Load data lịch sử song song bằng Promise.all với SessionStorage caching.
 * Đảm bảo tận dụng tối đa băng thông mà vẫn tránh Rate Limit.
 */
async function fetchHistoricalDataParallel() {
    if (!CONFIG.username || !CONFIG.key) return;
    const baseUrl = `https://io.adafruit.com/api/v2/${CONFIG.username}/feeds`;
    const headers = { 'X-AIO-Key': CONFIG.key };

    // v5.0: Load lich su tu feed batch "sensor-data" thay vi 5 feeds rieng
    // Moi data point la 1 JSON chua tat ca sensor -> giai ma va phan phoi
    const sensorKeys = ['soil_moisture', 'temperature', 'light_intensity', 'humidity', 'co2_level', 'ec_level', 'ph_level'];
    const sensorMap  = {
        soil_moisture:   'moisture',
        temperature:     'temperature',
        light_intensity: 'light',
        humidity:        'humidity',
        co2_level:       'co2',
        ec_level:        'ec',
        ph_level:        'ph',
    };
    const feedKey  = CONFIG.feeds.sensorData;
    const cacheKey = `aio_cache_${feedKey}`;
    const cached   = sessionStorage.getItem(cacheKey);
    const cacheTime = sessionStorage.getItem(`${cacheKey}_time`);

    let rawData = null;
    if (cached && cacheTime && (Date.now() - parseInt(cacheTime)) < 60000) {
        rawData = JSON.parse(cached);
    }
    if (!rawData) {
        try {
            const res = await fetch(`${baseUrl}/${feedKey}/data?limit=30`, { headers });
            if (res.status === 429) { console.error('[REST] Rate Limit (429) tai sensor-data!'); }
            else if (res.ok) {
                rawData = await res.json();
                sessionStorage.setItem(cacheKey, JSON.stringify(rawData));
                sessionStorage.setItem(`${cacheKey}_time`, Date.now().toString());
            }
        } catch (e) { console.warn('[REST] Loi load lich su sensor-data:', e); }
    }

    if (rawData && Array.isArray(rawData)) {
        // Moi item la 1 JSON string -> giai ma va phan phoi ra tung sensor
        const buckets = Object.fromEntries(sensorKeys.map(k => [k, []]));
        rawData.slice().reverse().forEach(pt => {
            try {
                const d   = JSON.parse(pt.value);
                const ts  = new Date(pt.created_at).toLocaleTimeString('vi-VN');
                sensorKeys.forEach(k => {
                    const v = parseFloat(d[k]);
                    if (!isNaN(v)) buckets[k].push({ value: v, time: ts });
                });
            } catch (_) {}
        });
        sensorKeys.forEach(k => {
            const uiKey = sensorMap[k];
            if (buckets[k].length > 0) {
                loadBulkHistory(uiKey, buckets[k]);
                updateGauge(uiKey, buckets[k][buckets[k].length - 1].value);
            }
        });
    }

    // Fallback: van load 5 feed rieng neu sensor-data chua co data
    // (su dung trong giai doan chuyen doi hoac khi deploy len server moi)
    const sensors = ['moisture', 'temperature', 'light', 'humidity', 'co2'];
    
    console.log('[REST] Đang load data lịch sử fallback (song song)...');
    
    const fetchPromises = sensors.map(async (sensor) => {
        const feedKey = CONFIG.feeds[sensor];
        const cacheKey = `aio_cache_${feedKey}`;
        const cached = sessionStorage.getItem(cacheKey);
        const cacheTime = sessionStorage.getItem(`${cacheKey}_time`);
        
        let data = null;
        
        // Neu co cache va chua qua 1 phut (60000ms), dung luon cache
        if (cached && cacheTime) {
            const age = Date.now() - parseInt(cacheTime);
            if (age < 60000) {
                data = JSON.parse(cached);
            }
        }
        
        if (!data) {
            try {
                const res = await fetch(`${baseUrl}/${feedKey}/data?limit=30`, { headers });
                if (res.status === 429) {
                    console.error(`[REST] Adafruit IO Rate Limit (429) tai feed ${sensor}!`);
                    return null;
                }
                if (!res.ok) return null;
                
                data = await res.json();
                sessionStorage.setItem(cacheKey, JSON.stringify(data));
                sessionStorage.setItem(`${cacheKey}_time`, Date.now().toString());
            } catch (e) {
                console.warn(`[REST] Loi load data lich su ${sensor}:`, e);
                return null;
            }
        }
        
        if (!data) return null;
        
        const parsedData = data
            .reverse()
            .map(p => ({
                value: parseFloat(p.value),
                time:  new Date(p.created_at).toLocaleTimeString('vi-VN'),
            }))
            .filter(p => !isNaN(p.value));

        return { sensor, parsedData };
    });

    // Chờ tất cả các request chạy song song hoàn thành
    const results = await Promise.all(fetchPromises);

    // Xử lý và cập nhật UI sau khi load xong
    for (const result of results) {
        if (result && result.parsedData.length > 0) {
            loadBulkHistory(result.sensor, result.parsedData);
            updateGauge(result.sensor, result.parsedData[result.parsedData.length - 1].value);
        }
    }
    
    // FIX Bug An 11: Mo khoa cho phep nhan du lieu real-time tu MQTT
    historyLoaded = true;
    console.log('[REST] Đã load xong data lịch sử song song an toàn. Mo khoa Real-time MQTT.');
}
