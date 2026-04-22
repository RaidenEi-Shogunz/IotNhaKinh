import { CONFIG, state } from './config.js';
import {
    updateConnectionStatus, updateGauge, updatePumpDisplay,
    updateModeDisplay, updatePIDDisplay, updateAIDisplay,
    addWateringLogFromEvent, addAlert, syncSimClock
} from './uiController.js';
import { addHistory, loadBulkHistory } from './chartManager.js';
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
            const isSensorFeed = Object.values(CONFIG.feeds).includes(feed) && 
                                 ['moisture', 'temperature', 'light', 'humidity', 'co2'].some(s => CONFIG.feeds[s] === feed);
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

    if (feed === f.moisture) {
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

    const sensors = ['moisture', 'temperature', 'light', 'humidity', 'co2'];
    
    console.log('[REST] Đang load data lịch sử (song song) kèm Session Caching...');
    
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
