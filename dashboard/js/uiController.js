import { DOM, CONFIG, state } from './config.js';
import { escapeHtml } from './utils.js';
import { initChart, refreshChart } from './chartManager.js';

export function cacheDOMElements() {
    ['moisture', 'temperature', 'light', 'humidity', 'co2', 'ec', 'ph'].forEach(type => {
        DOM.gauges[type]   = document.getElementById(`gauge-${type}`);
        DOM.values[type]   = document.getElementById(`val-${type}`);
        DOM.statuses[type] = document.getElementById(`status-${type}`);
    });
    DOM.simClock         = document.getElementById('sim-clock');
    DOM.weatherDisplay   = document.getElementById('weather-display');
    DOM.connectionStatus = document.getElementById('mqtt-status');
    DOM.pumpStatus       = document.getElementById('pump-status-text');
    DOM.aiDisplay        = document.getElementById('ai-status');
    DOM.alertList        = document.getElementById('alert-list');
    DOM.chartTabs        = document.querySelectorAll('.chart-tabs .tab');
    DOM.lastUpdate       = document.getElementById('last-update');
}

const GAUGE_CIRCUMFERENCE = 2 * Math.PI * 52;

// Luu gia tri truoc do de tinh trend
const _prevValues = {};

export function updateGauge(type, value) {
    const max    = CONFIG.gaugeMax[type];
    const ratio  = Math.max(0, Math.min(value / max, 1));
    const offset = GAUGE_CIRCUMFERENCE * (1 - ratio);

    const gauge    = DOM.gauges[type];
    const valEl    = DOM.values[type];
    const statusEl = DOM.statuses[type];

    if (gauge)    gauge.style.strokeDashoffset = offset;
    if (valEl)    valEl.textContent = (type === 'light' || type === 'co2')
                    ? Math.round(value)
                    : value.toFixed(1);
    if (statusEl) {
        statusEl.textContent = getSensorStatus(type, value);
        statusEl.style.color = getSensorColor(type, value);
    }

    // UX: Flash animation khi gia tri thay doi
    const card = document.getElementById(`card-${type}`);
    if (card && _prevValues[type] !== undefined && _prevValues[type] !== value) {
        card.classList.remove('flash');
        void card.offsetWidth; // Force reflow
        card.classList.add('flash');
    }

    // UX: Trend indicator (↑↓→)
    if (valEl && _prevValues[type] !== undefined) {
        let trendEl = valEl.parentElement?.querySelector('.trend-indicator');
        if (!trendEl) {
            trendEl = document.createElement('span');
            trendEl.className = 'trend-indicator';
            valEl.parentElement?.appendChild(trendEl);
        }
        const diff = value - _prevValues[type];
        if (Math.abs(diff) < 0.05) {
            trendEl.textContent = '→';
            trendEl.className = 'trend-indicator flat';
        } else if (diff > 0) {
            trendEl.textContent = '↑';
            trendEl.className = 'trend-indicator up';
        } else {
            trendEl.textContent = '↓';
            trendEl.className = 'trend-indicator down';
        }
    }

    _prevValues[type] = value;

    // UX: Cap nhat "last update" timestamp
    if (DOM.lastUpdate) {
        const now = new Date();
        DOM.lastUpdate.textContent = `⏱ ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
        DOM.lastUpdate.classList.add('fresh');
        clearTimeout(DOM._lastUpdateTimer);
        DOM._lastUpdateTimer = setTimeout(() => DOM.lastUpdate.classList.remove('fresh'), 3000);
    }
}

function getSensorStatus(type, val) {
    const checks = {
        moisture:    () => val < 30 ? 'Thấp!' : val > 80 ? 'Cao!' : 'Bình thường',
        temperature: () => val > 40 ? 'Quá nóng!' : val < 15 ? 'Quá lạnh!' : 'Bình thường',
        light:       () => val > 40000 ? 'Quá mạnh!' : val < 100 ? 'Tối' : 'Bình thường',
        humidity:    () => val < 30 ? 'Khô!' : val > 85 ? 'Ẩm!' : 'Bình thường',
        co2:         () => val > 1000 ? 'Cao!' : val < 300 ? 'Thấp' : 'Bình thường',
        ec:          () => val > 3.5 ? 'Quá mặn!' : val < 0.5 ? 'Quá nhạt' : 'Bình thường',
        ph:          () => val > 7.5 ? 'Kiềm!' : val < 5.5 ? 'Acid!' : 'Bình thường',
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
        ec:          () => val > 3.5 ? danger : val < 0.5 ? warn : ok,
        ph:          () => val > 7.5 ? warn : val < 5.5 ? warn : ok,
    };
    return (checks[type] || (() => ok))();
}

export function updateConnectionStatus(status) {
    const el      = DOM.connectionStatus;
    const overlay = document.getElementById('connection-overlay');
    if (!el) return;
    if (status === 'online') {
        el.className = 'status-dot online';
        el.innerHTML = '&#9679; Đã kết nối';
        if (overlay) overlay.classList.add('hidden');
    } else if (status === 'reconnecting') {
        el.className = 'status-dot reconnecting';
        el.innerHTML = '&#9679; Đang kết nối lại...';
        if (overlay) overlay.classList.remove('hidden');
    } else {
        el.className = 'status-dot offline';
        el.innerHTML = '&#9679; Mất kết nối';
        if (overlay) overlay.classList.remove('hidden');
    }
}

export function updatePumpDisplay(on) {
    const display = document.getElementById('pump-display');
    const btn     = document.getElementById('btn-pump');
    const text    = DOM.pumpStatus;
    if (on) {
        if (display) display.classList.add('active');
        if (btn)  { btn.className = 'btn-pump on'; btn.textContent = 'BẬT'; }
        if (text)   text.textContent = 'ĐANG CHẠY';
    } else {
        if (display) display.classList.remove('active');
        if (btn)  { btn.className = 'btn-pump off'; btn.textContent = 'TẮT'; }
        if (text)   text.textContent = 'TẮT';
    }
    if (btn) btn.disabled = state.currentMode === 'AUTO';
}

export function updateModeDisplay() {
    const isAuto    = state.currentMode === 'AUTO';
    const btnAuto   = document.getElementById('btn-auto');
    const btnManual = document.getElementById('btn-manual');
    const btnPump   = document.getElementById('btn-pump');
    if (btnAuto)   btnAuto.classList.toggle('active', isAuto);
    if (btnManual) btnManual.classList.toggle('active', !isAuto);
    if (btnPump)   btnPump.disabled = isAuto;
}

export function updatePIDDisplay(output, setpoint) {
    const bar   = document.getElementById('pid-bar');
    const outEl = document.getElementById('pid-output');
    const spEl  = document.getElementById('pid-setpoint');
    if (bar)   bar.style.width   = Math.min(100, Math.max(0, output)) + '%';
    if (outEl) outEl.textContent = output.toFixed(1) + '%';
    if (spEl)  spEl.textContent  = setpoint.toFixed(1) + '%';
}

export function updateAIDisplay(ai) {
    const statusEl = DOM.aiDisplay;
    const recEl    = document.getElementById('ai-recommendation');
    const colors   = {
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

export function addWateringLogFromEvent(event) {
    state.wateringLog.unshift(event);
    if (state.wateringLog.length > 30) state.wateringLog.pop();

    const tbody = document.getElementById('log-body');
    if (!tbody) return;

    const fragment = document.createDocumentFragment();
    state.wateringLog.forEach(log => {
        const simTime  = escapeHtml(log.sim_time  || '--');
        const realTime = escapeHtml(log.real_time || '--');
        const action   = log.action === 'ON' ? 'ON' : 'OFF';
        const color    = action === 'ON' ? 'var(--color-pump-on)' : 'var(--color-pump-off)';
        const icon     = action === 'ON' ? '💧 BẬT' : '■ TẮT';
        const moisture = log.moisture != null ? log.moisture.toFixed(1) + '%' : '--';
        const trigger  = escapeHtml(log.trigger || '--');
        const tr       = document.createElement('tr');
        tr.innerHTML   = `
            <td title="Giờ thực: ${realTime}">${simTime}</td>
            <td style="color:${color}">${icon}</td>
            <td>${moisture}</td>
            <td>${trigger}</td>
        `;
        fragment.appendChild(tr);
    });
    tbody.innerHTML = '';
    tbody.appendChild(fragment);
}

export function addAlert(severity, message, time) {
    state.alerts.unshift({ severity, message, time });
    if (state.alerts.length > 20) state.alerts.pop();
    renderAlerts();
}

function renderAlerts() {
    const el = document.getElementById('alert-list');
    if (!el) return;
    if (state.alerts.length === 0) {
        el.innerHTML = '<div class="empty-row">Không có cảnh báo</div>';
        return;
    }
    const fragment = document.createDocumentFragment();
    state.alerts.forEach(a => {
        const div       = document.createElement('div');
        div.className   = `alert-item ${escapeHtml(a.severity)}`;
        div.innerHTML   = `
            <span class="alert-time">${escapeHtml(a.time)}</span>
            <span class="alert-msg">${escapeHtml(a.message)}</span>
            <span class="alert-severity">${escapeHtml(a.severity)}</span>
        `;
        fragment.appendChild(div);
    });
    el.innerHTML = '';
    el.appendChild(fragment);
}

export function toggleTheme() {
    const html    = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next    = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const btnTheme = document.getElementById('btn-theme');
    if (btnTheme) btnTheme.textContent = next === 'dark' ? '\u263E' : '\u2600';
    initChart(true);
    refreshChart();
}

export function loadTheme() {
    const saved    = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    const btnTheme = document.getElementById('btn-theme');
    if (btnTheme) btnTheme.textContent = saved === 'dark' ? '\u263E' : '\u2600';
}

export let _lastMqttSyncMs = 0;

/**
 * Dong bo dong ho mo phong tu MQTT.
 * NANG CAP: Fallback noi suy thoi gian khi mat ket noi (thay vi hien thi '--:--')
 */
export function syncSimClock(simTimeStr, weatherCondition = '') {
    _lastMqttSyncMs       = Date.now();
    state.lastSimTime     = simTimeStr;
    state.currentSimTime  = simTimeStr;

    // Luu gia tri phut mo phong de noi suy
    const parts = simTimeStr.split(':');
    if (parts.length === 2) {
        state._simMinutesAtSync = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
        state._realMsAtSync     = _lastMqttSyncMs;
    }

    if (DOM.simClock) DOM.simClock.textContent = simTimeStr;

    if (DOM.weatherDisplay && simTimeStr) {
        const h     = parseInt(simTimeStr.split(':')[0], 10);
        const isDay = h >= 6 && h < 20;
        let timeStr    = isDay ? '\u2600 Ban ngay' : '\u263E Ban dem';
        let weatherStr = '';
        if (weatherCondition === 'rainy')       weatherStr = ' | \uD83C\uDF27\uFE0F Mua';
        else if (weatherCondition === 'cloudy') weatherStr = ' | \u2601\uFE0F Nhieu may';
        else if (weatherCondition === 'clear')  weatherStr = ' | \uD83C\uDF24\uFE0F Troi quang';
        DOM.weatherDisplay.textContent = timeStr + weatherStr;
    }
}

/**
 * NANG CAP: Noi suy thoi gian mo phong giua cac lan MQTT sync.
 * Thay vi hien thi '--:--' sau 2 phut, tinh toan va tien len theo TIME_SCALE.
 * TIME_SCALE mac dinh = 10 (1 phut thuc = 10 phut mo phong).
 */
export function startSimClockFallback(timeScale = 10) {
    setInterval(() => {
        if (!DOM.simClock) return;
        const now   = Date.now();
        const msSince = now - _lastMqttSyncMs;

        if (msSince > 5000 && state._simMinutesAtSync != null) {
            // Noi suy: so phut mo phong da qua = so phut thuc * TIME_SCALE
            const realMinutesSince = msSince / 60000;
            const simMinutesTotal  = (state._simMinutesAtSync + realMinutesSince * timeScale) % (24 * 60);
            const h = Math.floor(simMinutesTotal / 60);
            const m = Math.floor(simMinutesTotal % 60);
            DOM.simClock.textContent = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
        }
    }, 1000);
}
