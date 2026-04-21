/**
 * Nha Kinh Thong Minh - Dashboard JavaScript
 * =============================================
 * Dashboard phan anh chinh xac trang thai CMD:
 *   - Do am, nhiet do, anh sang, do am KK, CO2
 *   - Trang thai bom (ON/OFF), che do (AUTO/MANUAL)
 *   - Dong ho mo phong dong bo tu MQTT
 *   - PID controller output / setpoint
 *   - Nhat ky tuoi + Canh bao
 *
 * FIX [1]: reconnectPeriod tang 15000ms, them keepalive:60 tranh reconnect storm
 * FIX [2]: Subscribe voi QoS 0 (giam overhead, Adafruit IO free tier)
 * FIX [3]: PID display lay tu ai-status payload (pid_output, pid_setpoint)
 * FIX [4]: updateConnectionStatus xu ly ca trang thai 'reconnect' rieng biet
 * FIX [5]: Credentials check hien thi loi ro rang
 * FIX [6]: escapeHtml bao ve XSS toan bo innerHTML
 * FIX [7]: Chart destroy/recreate khi doi theme tranh memory leak
 * FIX [8]: Dong ho fallback chi chay khi chua co MQTT sync > 60 giay
 */

// === CAU HINH ===
const _metaUser = document.querySelector('meta[name="adafruit-username"]');
const _metaKey  = document.querySelector('meta[name="adafruit-key"]');

const CONFIG = {
    username: _metaUser ? _metaUser.content.trim() : '',
    key:      _metaKey  ? _metaKey.content.trim()  : '',
mqttUrl: 'wss://io.adafruit.com/mqtt',
    feeds: {
        moisture:      'soil-moisture',
        temperature:   'temperature',
        light:         'light-intensity',
        humidity:      'humidity',
        co2:           'co2-level',
        pumpStatus:    'pump-status',
        pumpCmd:       'pump-cmd',
        mode:          'greenhouse-mode',
        threshold:     'moisture-threshold',
        aiStatus:      'ai-status',
        wateringEvent: 'watering-event',
        alertStatus:   'alert-status',
    },
    gaugeMax: {
        moisture:    100,
        temperature: 50,
        light:       12000,
        humidity:    100,
        co2:         1200,
    },
    maxDataPoints: 50,
};

// Freeze CONFIG for performance
Object.freeze(CONFIG);

// === DOM CACHE (Hieu nang) ===
const DOM = {
    // Gauges
    gauges: {},
    values: {},
    statuses: {},
    // UI elements
    simClock: null,
    weatherDisplay: null,
    connectionStatus: null,
    pumpStatus: null,
    aiDisplay: null,
    alertList: null,
    chartTabs: null,
};

// Cache DOM elements khi load
function cacheDOMElements() {
    // Gauges
    ['moisture', 'temperature', 'light', 'humidity', 'co2'].forEach(type => {
        DOM.gauges[type] = document.getElementById(`gauge-${type}`);
        DOM.values[type] = document.getElementById(`val-${type}`);
        DOM.statuses[type] = document.getElementById(`status-${type}`);
    });

    // UI elements
    DOM.simClock = document.getElementById('sim-clock');
    DOM.weatherDisplay = document.getElementById('weather-display');
    DOM.connectionStatus = document.getElementById('mqtt-status'); // Sua lai id dung
    DOM.pumpStatus = document.getElementById('pump-status-text');
    // DOM.modeDisplay khong su dung
    DOM.aiDisplay = document.getElementById('ai-status');
    // DOM.pidDisplay khong su dung
    DOM.alertList = document.getElementById('alert-list');
    // DOM.wateringLog khong su dung
    DOM.chartTabs = document.querySelectorAll('.chart-tabs .tab');
}

// === UTILITY FUNCTIONS ===
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Debounced chart refresh (tranh update qua thuong xuyen)
const debouncedRefreshChart = debounce(refreshChart, 100);

// Batch DOM updates for performance
let domUpdateQueue = [];
let rafId = null;

function queueDOMUpdate(updateFn) {
    domUpdateQueue.push(updateFn);
    if (!rafId) {
        rafId = requestAnimationFrame(() => {
            domUpdateQueue.forEach(fn => fn());
            domUpdateQueue = [];
            rafId = null;
        });
    }
}

// === XSS PROTECTION ===
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// === TRANG THAI ===
const state = {
    connected:   false,
    currentMode: 'AUTO',
    pumpOn:      false,
    activeChart: 'moisture',
    msgCount:    0,
    currentSimTime: '06:00', // Thoi gian mo phong (chi luu trong state, khong hien thi)
    history: {
        timestamps:  [],
        moisture:    [],
        temperature: [],
        light:       [],
        humidity:    [],
        co2:         [],
    },
    alerts:      [],
    wateringLog: [],
    lastSimTime: null,
};

const GAUGE_CIRCUMFERENCE = 2 * Math.PI * 52;

// === MQTT ===
let client = null;

function connectMQTT() {
    // FIX [5]: Kiem tra credentials ro rang
    if (!CONFIG.username || !CONFIG.key ||
        CONFIG.username === 'YOUR_USERNAME_HERE' ||
        CONFIG.key === 'YOUR_AIO_KEY_HERE') {
        const hint = document.getElementById('connection-hint');
        if (hint) {
            hint.textContent = 'Chua cau hinh credentials! Sua meta tag adafruit-username va adafruit-key trong index.html.';
            hint.style.color = 'var(--color-danger)';
        }
        console.error('[MQTT] Thieu credentials Adafruit IO');
        return;
    }

    // FIX [1]: Tang reconnectPeriod, them keepalive, clean:true
    const options = {
        username:        CONFIG.username,
        password:        CONFIG.key,
        clientId:        'dashboard_' + Math.random().toString(16).substr(2, 8),
        reconnectPeriod: 20000,
        connectTimeout:  15000,
        keepalive:       60,      // FIX: them keepalive 60 giay
        clean:           true,
        protocolVersion: 4,       // MQTT 3.1.1
    };

    client = mqtt.connect(CONFIG.mqttUrl, options);

    client.on('connect', () => {
        state.connected = true;
        updateConnectionStatus('online');
        console.log('[MQTT] Da ket noi!');

        // FIX [2]: Subscribe voi QoS 0 giam overhead
        Object.values(CONFIG.feeds).forEach(feed => {
            const topic = `${CONFIG.username}/feeds/${feed}`;
            client.subscribe(topic, { qos: 0 });
        });
    });

    client.on('message', (topic, message) => {
        const payload = message.toString().trim();
        const feed    = topic.split('/feeds/')[1];
        state.msgCount++;
        const counterEl = document.getElementById('msg-counter');
        if (counterEl) counterEl.textContent = `${state.msgCount} tin nhan`;
        handleMessage(feed, payload);
    });

    client.on('offline', () => {
        state.connected = false;
        updateConnectionStatus('offline');
    });

    client.on('reconnect', () => {
        // FIX [4]: Hien thi trang thai reconnect rieng biet
        updateConnectionStatus('reconnecting');
        console.log('[MQTT] Dang ket noi lai...');
    });

    client.on('error', (err) => {
        console.error('[MQTT] Loi:', err.message || err);
        state.connected = false;
        updateConnectionStatus('offline');
    });
}

function updateConnectionStatus(status) {
    const el      = DOM.connectionStatus;
    const overlay = document.getElementById('connection-overlay'); // Khong cache vi it su dung
    if (!el) return;

    // FIX [4]: 3 trang thai rieng biet
    if (status === 'online') {
        el.className     = 'status-dot online';
        el.innerHTML     = '&#9679; Da ket noi';
        if (overlay) overlay.classList.add('hidden');
    } else if (status === 'reconnecting') {
        el.className     = 'status-dot reconnecting';
        el.innerHTML     = '&#9679; Dang ket noi lai...';
        if (overlay) overlay.classList.remove('hidden');
    } else {
        el.className     = 'status-dot offline';
        el.innerHTML     = '&#9679; Mat ket noi';
        if (overlay) overlay.classList.remove('hidden');
    }
}

// === XU LY TIN NHAN ===
function handleMessage(feed, payload) {
    const f   = CONFIG.feeds;
    // Su dung thoi gian thuc cho bieu do, giu thoi gian mo phong cho dong ho
    const timestamp = new Date().toLocaleTimeString('vi-VN');

    if (feed === f.moisture) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('moisture', v); addHistory('moisture', v, timestamp); }
    }
    else if (feed === f.temperature) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('temperature', v); addHistory('temperature', v, timestamp); }
    }
    else if (feed === f.light) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('light', v); addHistory('light', v, timestamp); }
    }
    else if (feed === f.humidity) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('humidity', v); addHistory('humidity', v, timestamp); }
    }
    else if (feed === f.co2) {
        const v = parseFloat(payload);
        if (!isNaN(v)) { updateGauge('co2', v); addHistory('co2', v, timestamp); }
    }
    else if (feed === f.pumpStatus) {
        const on = payload.toUpperCase() === 'ON';
        state.pumpOn = on;
        updatePumpDisplay(on);
    }
    else if (feed === f.mode) {
        state.currentMode = payload.toUpperCase();
        updateModeDisplay();
    }
    else if (feed === f.aiStatus) {
        try {
            const ai = JSON.parse(payload);
            updateAIDisplay(ai);
            // FIX [3]: PID display tu ai payload
            if (ai.pid_output != null && ai.pid_setpoint != null) {
                updatePIDDisplay(ai.pid_output, ai.pid_setpoint);
            }
            // Dong ho mo phong
            if (ai.sim_time) syncSimClock(ai.sim_time);
            if (ai.sim_day != null) {
                const dayEl = document.getElementById('sim-day');
                if (dayEl) dayEl.textContent = `Ngay ${ai.sim_day}`;
            }
        } catch (e) {
            updateAIDisplay({ status: payload, confidence: 0, recommendation: '' });
        }
    }
    else if (feed === f.wateringEvent) {
        try {
            const event = JSON.parse(payload);
            addWateringLogFromEvent(event);
        } catch (e) {
            console.warn('[MQTT] Loi parse watering-event:', e);
        }
    }
    else if (feed === f.alertStatus) {
        try {
            const alert = JSON.parse(payload);
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

// === GAUGE ===
function updateGauge(type, value) {
    const max    = CONFIG.gaugeMax[type];
    const ratio  = Math.min(value / max, 1);
    const offset = GAUGE_CIRCUMFERENCE * (1 - ratio);

    // Su dung cached DOM elements
    const gauge    = DOM.gauges[type];
    const valEl    = DOM.values[type];
    const statusEl = DOM.statuses[type];

    if (gauge) gauge.style.strokeDashoffset = offset;
    if (valEl) {
        valEl.textContent = (type === 'light' || type === 'co2')
            ? Math.round(value)
            : value.toFixed(1);
    }
    if (statusEl) {
        statusEl.textContent = getSensorStatus(type, value);
        statusEl.style.color = getSensorColor(type, value);
    }
}

function getSensorStatus(type, val) {
    const checks = {
        moisture:    () => val < 30 ? 'Thap!' : val > 80 ? 'Cao!' : 'Binh thuong',
        temperature: () => val > 40 ? 'Qua nong!' : val < 15 ? 'Qua lanh!' : 'Binh thuong',
        light:       () => val > 40000 ? 'Qua manh!' : val < 100 ? 'Toi' : 'Binh thuong',
        humidity:    () => val < 30 ? 'Kho!' : val > 85 ? 'Am!' : 'Binh thuong',
        co2:         () => val > 1000 ? 'Cao!' : val < 300 ? 'Thap' : 'Binh thuong',
    };
    return (checks[type] || (() => ''))();
}

function getSensorColor(type, val) {
    const warn   = 'var(--color-warning)';
    const danger = 'var(--color-danger)';
    const ok     = 'var(--color-success)';
    const checks = {
        moisture:    () => val < 20 ? danger : val < 30 ? warn : val > 80 ? warn : ok,
        temperature: () => val > 40 ? danger : val > 35 ? warn : val < 15 ? warn : ok,
        light:       () => val > 40000 ? danger : ok,
        humidity:    () => val < 30 ? warn : val > 85 ? warn : ok,
        co2:         () => val > 1000 ? danger : ok,
    };
    return (checks[type] || (() => ok))();
}

// === LICH SU DU LIEU (BATCH) ===
let lastBatchMs       = 0;
const BATCH_WINDOW_MS = 3000;

function addHistory(type, value, timestamp) {
    const h   = state.history;
    const now = Date.now();

    if (now - lastBatchMs > BATCH_WINDOW_MS) {
        lastBatchMs = now;
        h.timestamps.push(timestamp);
        if (h.timestamps.length > CONFIG.maxDataPoints) h.timestamps.shift();

        ['moisture', 'temperature', 'light', 'humidity', 'co2'].forEach(key => {
            if (key !== type) {
                const arr = h[key];
                arr.push(arr.length > 0 ? arr[arr.length - 1] : NaN);
                if (arr.length > CONFIG.maxDataPoints) arr.shift();
            }
        });
    }

    const arr = h[type];
    if (arr.length < h.timestamps.length) {
        arr.push(value);
    } else if (arr.length > 0) {
        arr[arr.length - 1] = value;
    }
    if (arr.length > CONFIG.maxDataPoints) arr.shift();
    debouncedRefreshChart();
}

// === CHART.JS ===
let sensorChart = null;

const chartConfigs = {
    moisture:    { label: 'Do am dat (%)',  color: '#3b82f6', min: 0,   max: 100 },
    temperature: { label: 'Nhiet do (C)',   color: '#ef4444', min: 0,   max: 50  },
    light:       { label: 'Anh sang (lux)', color: '#f59e0b', min: 0,   max: 12000 },
    humidity:    { label: 'Do am KK (%)',   color: '#06b6d4', min: 0,   max: 100 },
    co2:         { label: 'CO2 (ppm)',      color: '#8b5cf6', min: 200, max: 1200 },
};

function initChart() {
    const canvas = document.getElementById('sensor-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const cfg = chartConfigs[state.activeChart];

    const isDark    = document.documentElement.getAttribute('data-theme') !== 'light';
    const tickColor = isDark ? '#94a3b8' : '#475569';
    const gridColor = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';

    sensorChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label:            cfg.label,
                data:             [],
                borderColor:      cfg.color,
                backgroundColor:  cfg.color + '20',
                borderWidth:      2,
                fill:             true,
                tension:          0.4,
                pointRadius:      2,
                pointHoverRadius: 5,
            }],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            animation:           { duration: 300 },
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    ticks: { color: tickColor, maxTicksLimit: 10, font: { size: 10 } },
                    grid:  { color: gridColor },
                },
                y: {
                    min:   cfg.min,
                    max:   cfg.max,
                    ticks: { color: tickColor, font: { size: 10 } },
                    grid:  { color: gridColor },
                },
            },
        },
    });
}

function refreshChart() {
    if (!sensorChart) return;
    const type = state.activeChart;
    const cfg  = chartConfigs[type];
    const h    = state.history;

    sensorChart.data.labels                       = [...h.timestamps];
    sensorChart.data.datasets[0].data             = [...h[type]];
    sensorChart.data.datasets[0].label            = cfg.label;
    sensorChart.data.datasets[0].borderColor      = cfg.color;
    sensorChart.data.datasets[0].backgroundColor  = cfg.color + '20';
    sensorChart.options.scales.y.min              = cfg.min;
    sensorChart.options.scales.y.max              = cfg.max;
    sensorChart.update('none');
}

function switchChart(type) {
    state.activeChart = type;
    // Su dung cached DOM elements
    DOM.chartTabs.forEach(t => {
        t.classList.toggle('active', t.dataset.chart === type);
    });
    refreshChart();
}

// === DIEU KHIEN BOM ===
function updatePumpDisplay(on) {
    const display = document.getElementById('pump-display'); // Khong cache vi it su dung
    const btn     = document.getElementById('btn-pump');
    const text    = DOM.pumpStatus;

    if (on) {
        if (display) display.classList.add('active');
        if (btn) { btn.className = 'btn-pump on'; btn.textContent = 'BAT'; }
        if (text) text.textContent = 'DANG CHAY';
    } else {
        if (display) display.classList.remove('active');
        if (btn) { btn.className = 'btn-pump off'; btn.textContent = 'TAT'; }
        if (text) text.textContent = 'TAT';
    }
    if (btn) btn.disabled = state.currentMode === 'AUTO';
}

function togglePump() {
    if (state.currentMode === 'AUTO') return;
    const newState = state.pumpOn ? 'OFF' : 'ON';
    publishMQTT(CONFIG.feeds.pumpCmd, newState);
}

function setMode(mode) {
    publishMQTT(CONFIG.feeds.mode, mode);
    state.currentMode = mode;
    updateModeDisplay();
}

function updateModeDisplay() {
    const isAuto = state.currentMode === 'AUTO';
    const btnAuto   = document.getElementById('btn-auto');   // Khong cache vi it su dung
    const btnManual = document.getElementById('btn-manual');
    const btnPump   = document.getElementById('btn-pump');
    if (btnAuto)   btnAuto.classList.toggle('active', isAuto);
    if (btnManual) btnManual.classList.toggle('active', !isAuto);
    if (btnPump)   btnPump.disabled = isAuto;
}

// === NGUONG DO AM ===
let thresholdTimer = null;
function onThresholdChange(val) {
    const el = document.getElementById('threshold-value');
    if (el) el.textContent = val + '%';
    clearTimeout(thresholdTimer);
    thresholdTimer = setTimeout(() => {
        publishMQTT(CONFIG.feeds.threshold, val);
    }, 500);
}

// === FIX [3]: PID DISPLAY - nhan tu ai payload ===
function updatePIDDisplay(output, setpoint) {
    const bar   = document.getElementById('pid-bar');
    const outEl = document.getElementById('pid-output');
    const spEl  = document.getElementById('pid-setpoint');
    if (bar)   bar.style.width   = Math.min(100, Math.max(0, output)) + '%';
    if (outEl) outEl.textContent = output.toFixed(1) + '%';
    if (spEl)  spEl.textContent  = setpoint.toFixed(1) + '%';
}

// === AI DISPLAY ===
function updateAIDisplay(ai) {
    const statusEl = DOM.aiDisplay;
    const recEl    = document.getElementById('ai-recommendation'); // Khong cache vi it su dung

    const colors = {
        'Binh thuong': 'var(--color-success)',
        'Thieu nuoc':  'var(--color-warning)',
        'Nguy hiem':   'var(--color-danger)',
    };

    if (statusEl) {
        const confidence   = ai.confidence ? (ai.confidence * 100).toFixed(0) : '0';
        statusEl.textContent = `${ai.status || '...'} (${confidence}%)`;
        statusEl.style.color = colors[ai.status] || 'var(--text-primary)';
    }
    if (recEl) recEl.textContent = ai.recommendation || '';
}

// === NHAT KY TUOI ===
function addWateringLogFromEvent(event) {
    state.wateringLog.unshift(event);
    if (state.wateringLog.length > 30) state.wateringLog.pop();

    const tbody = document.getElementById('log-body');
    if (!tbody) return;
    tbody.innerHTML = state.wateringLog.map(log => {
        const simTime  = escapeHtml(log.sim_time  || '--');
        const realTime = escapeHtml(log.real_time || '--');
        const action   = log.action === 'ON' ? 'ON' : 'OFF';
        const color    = action === 'ON' ? 'var(--color-pump-on)' : 'var(--color-pump-off)';
        const icon     = action === 'ON' ? '&#128167; BAT' : '&#9724; TAT';
        const moisture = log.moisture != null ? log.moisture.toFixed(1) + '%' : '--';
        const trigger  = escapeHtml(log.trigger || '--');
        return `<tr>
            <td title="Gio thuc: ${realTime}">${simTime}</td>
            <td style="color:${color}">${icon}</td>
            <td>${moisture}</td>
            <td>${trigger}</td>
        </tr>`;
    }).join('');
}

// === CANH BAO ===
function addAlert(severity, message, time) {
    state.alerts.unshift({ severity, message, time });
    if (state.alerts.length > 20) state.alerts.pop();
    renderAlerts();
}

function renderAlerts() {
    const el = document.getElementById('alert-list');
    if (!el) return;
    if (state.alerts.length === 0) {
        el.innerHTML = '<div class="empty-row">Khong co canh bao</div>';
        return;
    }
    el.innerHTML = state.alerts.map(a => `
        <div class="alert-item ${escapeHtml(a.severity)}">
            <span class="alert-time">${escapeHtml(a.time)}</span>
            <span class="alert-msg">${escapeHtml(a.message)}</span>
            <span class="alert-severity">${escapeHtml(a.severity)}</span>
        </div>`).join('');
}

// === PUBLISH MQTT ===
function publishMQTT(feed, value) {
    if (!client || !state.connected) return;
    const topic = `${CONFIG.username}/feeds/${feed}`;
    client.publish(topic, String(value), { qos: 0 });
    console.log(`[GUI] ${topic} = ${value}`);
}

// === DARK/LIGHT MODE ===
function toggleTheme() {
    const html    = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next    = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const btnTheme = document.getElementById('btn-theme');
    if (btnTheme) btnTheme.textContent = next === 'dark' ? '\u263E' : '\u2600';

    // FIX [7]: Destroy va tao lai chart tranh memory leak khi doi theme
    if (sensorChart) { sensorChart.destroy(); sensorChart = null; }
    initChart();
    refreshChart();
}

function loadTheme() {
    const saved   = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    const btnTheme = document.getElementById('btn-theme');
    if (btnTheme) btnTheme.textContent = saved === 'dark' ? '\u263E' : '\u2600';
}

// === EXPORT CSV ===
function exportCSV() {
    const h = state.history;
    if (h.timestamps.length === 0) { alert('Chua co du lieu de xuat!'); return; }
    let csv = 'Thoi gian,Do am dat (%),Nhiet do (C),Anh sang (lux),Do am KK (%),CO2 (ppm)\n';
    for (let i = 0; i < h.timestamps.length; i++) {
        csv += [
            h.timestamps[i]  || '',
            h.moisture[i]    ?? '',
            h.temperature[i] ?? '',
            h.light[i]       ?? '',
            h.humidity[i]    ?? '',
            h.co2[i]         ?? '',
        ].join(',') + '\n';
    }
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `nhakinh_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// === FIX [8]: Dong ho mo phong dong bo tu MQTT ===
let _lastMqttSyncMs = 0;

function syncSimClock(simTimeStr) {
    _lastMqttSyncMs     = Date.now();
    state.lastSimTime   = simTimeStr;
    state.currentSimTime = simTimeStr; // Dong bo thoi gian mo phong

    // Su dung thoi gian thuc thay vi thoi gian mo phong cho dong ho
    const realTimeStr = new Date().toLocaleTimeString('vi-VN');

    // Su dung cached DOM elements
    if (DOM.simClock) DOM.simClock.textContent = realTimeStr;
    if (DOM.weatherDisplay && simTimeStr) {
        const h     = parseInt(simTimeStr.split(':')[0], 10);
        const isDay = h >= 6 && h < 20;
        DOM.weatherDisplay.textContent = isDay ? '\u2600 Ban ngay' : '\u263E Ban dem';
    }
}

function startSimClockFallback() {
    // Su dung thoi gian thuc thay vi thoi gian mo phong
    setInterval(() => {
        // FIX [8]: Chi dung fallback neu chua co MQTT sync trong 60 giay
        if (_lastMqttSyncMs > 0 && (Date.now() - _lastMqttSyncMs) < 60000) return;
        const realTimeStr = new Date().toLocaleTimeString('vi-VN');
        if (DOM.simClock) DOM.simClock.textContent = realTimeStr;
    }, 1000);
}

// === KHOI TAO ===
document.addEventListener('DOMContentLoaded', () => {
    // Cache DOM elements for performance
    cacheDOMElements();

    loadTheme();
    initChart();
    connectMQTT();
    startSimClockFallback();

    document.querySelectorAll('.chart-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => switchChart(tab.dataset.chart));
    });

    const btnPump   = document.getElementById('btn-pump');
    const btnAuto   = document.getElementById('btn-auto');
    const btnManual = document.getElementById('btn-manual');
    const slider    = document.getElementById('threshold-slider');
    const btnTheme  = document.getElementById('btn-theme');
    const btnExport = document.getElementById('btn-export');

    if (btnPump)   btnPump.addEventListener('click', togglePump);
    if (btnAuto)   btnAuto.addEventListener('click', () => setMode('AUTO'));
    if (btnManual) btnManual.addEventListener('click', () => setMode('MANUAL'));
    if (slider)    slider.addEventListener('input', () => onThresholdChange(slider.value));
    if (btnTheme)  btnTheme.addEventListener('click', toggleTheme);
    if (btnExport) btnExport.addEventListener('click', exportCSV);
});
