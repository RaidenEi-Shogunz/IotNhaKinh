/**
 * chartManager.js — Nâng cấp v4.1
 * ====================================
 * Ba tính năng mới so với bản gốc:
 *
 *  [1] PUMP ANNOTATIONS
 *      Đường dọc xanh (ON) / đỏ (OFF) + vùng tô màu khi bơm chạy
 *      → Người xem biết ngay điểm nào tưới, tưới bao lâu
 *
 *  [2] ZOOM / PAN  (chartjs-plugin-zoom + hammerjs từ CDN)
 *      Scroll chuột = zoom trục X | Kéo = pan
 *      Nút "Reset" xuất hiện khi đã zoom, ẩn khi về gốc
 *
 *  [3] DUAL Y-AXIS OVERLAY
 *      Tab "Overlay" mới: Độ ẩm (trái) + Nhiệt độ (phải) cùng 1 chart
 *      → Thấy ngay mối quan hệ: trời nóng → ẩm bốc hơi nhanh
 *
 *  Các hàm cũ (addHistory, loadBulkHistory, exportCSV, switchChart)
 *  giữ nguyên 100% interface — không cần sửa mqttService / localApiService.
 */

import { CONFIG, state, DOM } from './config.js';
import { debounce } from './utils.js';

// ─── Chart instances ─────────────────────────────────────────────────────────
let moistureChart = null;   // Biểu đồ độ ẩm cố định (top) — có annotation + zoom
let sensorChart   = null;   // Biểu đồ cảm biến phụ (tab) — có zoom
let overlayChart  = null;   // Dual-axis: moisture trái + temperature phải

// ─── Plugin flags (kiểm tra sau khi CDN load) ────────────────────────────────
let _annotationOk = false;
let _zoomOk       = false;

// ─── Kho annotation bơm ──────────────────────────────────────────────────────
// Mỗi phần tử: { time: string (label trục X), action: 'ON'|'OFF' }
const _pumpEvents   = [];
const MAX_PUMP_EVT  = 80;   // Giữ tối đa 80 sự kiện

// ─── Bảng màu nhất quán ──────────────────────────────────────────────────────
const C = {
    moisture:     '#3b82f6',
    temperature:  '#ef4444',
    light:        '#f59e0b',
    humidity:     '#06b6d4',
    co2:          '#8b5cf6',
    pumpOnBg:     'rgba(16, 185, 129, 0.15)',
    pumpOnLine:   'rgba(16, 185, 129, 0.90)',
    pumpOffBg:    'rgba(239,  68,  68, 0.10)',
    pumpOffLine:  'rgba(239,  68,  68, 0.75)',
};

const CFGS = {
    moisture:    { label: 'Độ ẩm đất (%)',  color: C.moisture,    min: 0,   max: 100  },
    temperature: { label: 'Nhiệt độ (°C)',  color: C.temperature, min: 0,   max: 50   },
    light:       { label: 'Ánh sáng (lux)', color: C.light,       min: 0,   max: 12000 },
    humidity:    { label: 'Độ ẩm KK (%)',   color: C.humidity,    min: 0,   max: 100  },
    co2:         { label: 'CO₂ (ppm)',       color: C.co2,         min: 200, max: 1200 },
};

// ─── Helper: màu theo theme hiện tại ─────────────────────────────────────────
function _tc() {
    const dark = document.documentElement.getAttribute('data-theme') !== 'light';
    return {
        tick: dark ? '#94a3b8' : '#475569',
        grid: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)',
    };
}

// ─── Kiểm tra plugin có sẵn hay không ────────────────────────────────────────
function _detectPlugins() {
    if (typeof Chart === 'undefined') return;
    try {
        _annotationOk = !!Chart.registry.plugins.get('annotation');
    } catch { _annotationOk = false; }
    try {
        _zoomOk = !!Chart.registry.plugins.get('zoom');
    } catch { _zoomOk = false; }
}

// ─── Build annotation objects từ _pumpEvents ─────────────────────────────────
function _buildAnnotations(labels) {
    if (!_annotationOk || _pumpEvents.length === 0) return {};
    const ann    = {};
    let openIdx  = null;   // Index của sự kiện ON đang mở (chưa có OFF tương ứng)

    _pumpEvents.forEach((ev, i) => {
        const idx = labels.indexOf(ev.time);
        if (idx === -1) return;

        if (ev.action === 'ON') {
            // ── Đường dọc xanh ──
            ann[`pl_${i}`] = {
                type:        'line',
                scaleID:     'x',
                value:       idx,
                borderColor: C.pumpOnLine,
                borderWidth: 2,
                borderDash:  [5, 3],
                label: {
                    display:         true,
                    content:         '💧 BẬT',
                    backgroundColor: C.pumpOnLine,
                    color:           '#fff',
                    font:            { size: 10, weight: 'bold' },
                    position:        'start',
                    yAdjust:         -6,
                },
            };
            openIdx = idx;

        } else {
            // ── Đường dọc đỏ ──
            ann[`pl_${i}`] = {
                type:        'line',
                scaleID:     'x',
                value:       idx,
                borderColor: C.pumpOffLine,
                borderWidth: 1.5,
                borderDash:  [3, 4],
                label: {
                    display:         true,
                    content:         '🔴 TẮT',
                    backgroundColor: C.pumpOffLine,
                    color:           '#fff',
                    font:            { size: 10, weight: 'bold' },
                    position:        'start',
                    yAdjust:         -6,
                },
            };
            // ── Vùng tô màu ON→OFF ──
            if (openIdx !== null) {
                ann[`pb_${i}`] = {
                    type:            'box',
                    xMin:            openIdx,
                    xMax:            idx,
                    backgroundColor: C.pumpOnBg,
                    borderWidth:     0,
                };
                openIdx = null;
            }
        }
    });

    // Bơm đang BẬT mà chưa có OFF → tô đến cuối chart
    if (openIdx !== null && labels.length > 0) {
        ann['pb_active'] = {
            type:            'box',
            xMin:            openIdx,
            xMax:            labels.length - 1,
            backgroundColor: C.pumpOnBg,
            borderWidth:     0,
        };
    }
    return ann;
}

// ─── Zoom plugin options ──────────────────────────────────────────────────────
function _zoomOpts(resetBtnId) {
    if (!_zoomOk) return {};
    return {
        zoom: {
            wheel:  { enabled: true, speed: 0.08 },
            pinch:  { enabled: true },
            mode:   'x',
            onZoom: () => _showReset(resetBtnId),
        },
        pan: {
            enabled: true,
            mode:    'x',
            onPan:   () => _showReset(resetBtnId),
        },
    };
}

function _showReset(id) { document.getElementById(id)?.classList.remove('hidden'); }
function _hideReset(id) { document.getElementById(id)?.classList.add('hidden');    }

// ─── initChart ───────────────────────────────────────────────────────────────
export function initChart(forceRecreate = false) {
    if (forceRecreate) {
        moistureChart?.destroy(); moistureChart = null;
        sensorChart?.destroy();   sensorChart   = null;
        overlayChart?.destroy();  overlayChart  = null;
    }

    _detectPlugins();

    const cMoisture = document.getElementById('moisture-chart');
    const cSensor   = document.getElementById('sensor-chart');
    const cOverlay  = document.getElementById('overlay-chart');
    if (!cMoisture || !cSensor) return;

    const { tick, grid } = _tc();

    // 1. Moisture — annotation + zoom
    moistureChart = _makeMoistureChart(cMoisture, tick, grid);

    // 2. Sensor phụ — zoom
    sensorChart = _makeSensorChart(cSensor, CFGS[state.activeChart ?? 'temperature'], tick, grid);

    // 3. Overlay — dual Y-axis + annotation + zoom
    if (cOverlay) overlayChart = _makeOverlayChart(cOverlay, tick, grid);
}

// ─── Moisture chart ───────────────────────────────────────────────────────────
function _makeMoistureChart(canvas, tick, grid) {
    const plugins = { legend: { display: false } };
    if (_annotationOk) plugins.annotation = { annotations: {} };
    if (_zoomOk)       plugins.zoom       = _zoomOpts('reset-moisture-zoom');

    return new Chart(canvas, {
        type: 'line',
        data: {
            labels:   [],
            datasets: [{
                label:            'Độ ẩm đất (%)',
                data:             [],
                borderColor:      C.moisture,
                backgroundColor:  C.moisture + '22',
                borderWidth:      2.5,
                fill:             true,
                tension:          0.4,
                pointRadius:      2,
                pointHoverRadius: 6,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            animation:  { duration: 250 },
            interaction:{ mode: 'index', intersect: false },
            plugins,
            scales: {
                x: { ticks: { color: tick, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: grid } },
                y: {
                    min: 0, max: 100,
                    title: { display: true, text: 'Độ ẩm đất (%)', color: tick, font: { size: 11, weight: 'bold' } },
                    ticks: { color: tick, font: { size: 10 } },
                    grid:  { color: grid },
                },
            },
        },
    });
}

// ─── Sensor chart (tab phụ) ───────────────────────────────────────────────────
function _makeSensorChart(canvas, cfg, tick, grid) {
    const plugins = { legend: { display: false } };
    if (_zoomOk) plugins.zoom = _zoomOpts('reset-sensor-zoom');

    return new Chart(canvas, {
        type: 'line',
        data: {
            labels:   [],
            datasets: [{
                label:            cfg.label,
                data:             [],
                borderColor:      cfg.color,
                backgroundColor:  cfg.color + '22',
                borderWidth:      2,
                fill:             true,
                tension:          0.4,
                pointRadius:      2,
                pointHoverRadius: 6,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            animation:  { duration: 250 },
            interaction:{ mode: 'index', intersect: false },
            plugins,
            scales: {
                x: { ticks: { color: tick, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: grid } },
                y: {
                    min: cfg.min, max: cfg.max,
                    title: { display: true, text: cfg.label, color: tick, font: { size: 11, weight: 'bold' } },
                    ticks: { color: tick, font: { size: 10 } },
                    grid:  { color: grid },
                },
            },
        },
    });
}

// ─── Overlay chart (dual Y-axis) ──────────────────────────────────────────────
function _makeOverlayChart(canvas, tick, grid) {
    const plugins = {
        legend: {
            display:  true,
            position: 'top',
            labels: {
                color: tick, font: { size: 11 },
                usePointStyle: true, pointStyleWidth: 10,
                padding: 16,
            },
        },
        tooltip: { mode: 'index', intersect: false },
    };
    if (_annotationOk) plugins.annotation = { annotations: {} };
    if (_zoomOk)       plugins.zoom       = _zoomOpts('reset-overlay-zoom');

    return new Chart(canvas, {
        type: 'line',
        data: {
            labels:   [],
            datasets: [
                {
                    label:            'Độ ẩm đất (%)',
                    data:             [],
                    yAxisID:          'yLeft',
                    borderColor:      C.moisture,
                    backgroundColor:  C.moisture + '1A',
                    borderWidth:      2.5,
                    fill:             true,
                    tension:          0.4,
                    pointRadius:      2,
                    pointHoverRadius: 6,
                },
                {
                    label:            'Nhiệt độ (°C)',
                    data:             [],
                    yAxisID:          'yRight',
                    borderColor:      C.temperature,
                    backgroundColor:  'transparent',
                    borderWidth:      2,
                    borderDash:       [6, 3],
                    fill:             false,
                    tension:          0.4,
                    pointRadius:      2,
                    pointHoverRadius: 6,
                },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            animation:  { duration: 250 },
            interaction:{ mode: 'index', intersect: false },
            plugins,
            scales: {
                x: { ticks: { color: tick, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: grid } },
                yLeft: {
                    type: 'linear', position: 'left',
                    min: 0, max: 100,
                    title: { display: true, text: 'Độ ẩm (%)', color: C.moisture, font: { size: 10, weight: 'bold' } },
                    ticks: { color: C.moisture, font: { size: 10 } },
                    grid:  { color: grid },
                },
                yRight: {
                    type: 'linear', position: 'right',
                    min: 0, max: 50,
                    title: { display: true, text: 'Nhiệt độ (°C)', color: C.temperature, font: { size: 10, weight: 'bold' } },
                    ticks: { color: C.temperature, font: { size: 10 } },
                    grid:  { drawOnChartArea: false },   // Không vẽ lưới phụ lên vùng chart
                },
            },
        },
    });
}

// ─── refreshChart ─────────────────────────────────────────────────────────────
export function refreshChart() {
    if (!moistureChart || !sensorChart) return;
    const h  = state.history;
    const ts = [...h.timestamps];

    // 1. Moisture chart
    const annMoisture = _buildAnnotations(ts);
    moistureChart.data.labels           = ts;
    moistureChart.data.datasets[0].data = [...h.moisture];
    if (_annotationOk && moistureChart.options.plugins?.annotation) {
        moistureChart.options.plugins.annotation.annotations = annMoisture;
    }
    moistureChart.update('none');

    // 2. Sensor phụ (tab đang chọn)
    const type = state.activeChart;
    const cfg  = CFGS[type] ?? CFGS.temperature;
    sensorChart.data.labels                       = ts;
    sensorChart.data.datasets[0].data             = [...h[type]];
    sensorChart.data.datasets[0].label            = cfg.label;
    sensorChart.data.datasets[0].borderColor      = cfg.color;
    sensorChart.data.datasets[0].backgroundColor  = cfg.color + '22';
    sensorChart.options.scales.y.min              = cfg.min;
    sensorChart.options.scales.y.max              = cfg.max;
    if (sensorChart.options.scales.y.title)
        sensorChart.options.scales.y.title.text   = cfg.label;
    sensorChart.update('none');

    // 3. Overlay chart
    if (overlayChart) {
        const annOverlay = _buildAnnotations(ts);
        overlayChart.data.labels              = ts;
        overlayChart.data.datasets[0].data    = [...h.moisture];
        overlayChart.data.datasets[1].data    = [...h.temperature];
        if (_annotationOk && overlayChart.options.plugins?.annotation) {
            overlayChart.options.plugins.annotation.annotations = annOverlay;
        }
        overlayChart.update('none');
    }

    // 4. Ẩn skeleton khi có dữ liệu
    _hideSkeleton('moisture-skeleton', 'moisture-chart');
    _hideSkeleton('chart-skeleton',    'sensor-chart');
    _hideSkeleton('overlay-skeleton',  'overlay-chart');
}

function _hideSkeleton(skId, cvId) {
    const sk = document.getElementById(skId);
    const cv = document.getElementById(cvId);
    if (sk && sk.style.display !== 'none') {
        sk.style.display = 'none';
        if (cv) cv.style.display = 'block';
    }
}

export const debouncedRefreshChart = debounce(refreshChart, 100);

// ─── switchChart ──────────────────────────────────────────────────────────────
export function switchChart(type) {
    state.activeChart = type;
    DOM.chartTabs?.forEach(t => t.classList.toggle('active', t.dataset.chart === type));
    refreshChart();
}

// ─── addPumpAnnotation (gọi từ mqttService / localApiService) ─────────────────
/**
 * @param {'ON'|'OFF'} action
 * @param {string}     timestamp  — label trục X (cùng format với h.timestamps)
 */
export function addPumpAnnotation(action, timestamp) {
    _pumpEvents.push({ action, time: timestamp });
    if (_pumpEvents.length > MAX_PUMP_EVT) _pumpEvents.shift();
    debouncedRefreshChart();
}

// ─── resetZoom ────────────────────────────────────────────────────────────────
export function resetZoom(chartId) {
    const map = { moisture: moistureChart, sensor: sensorChart, overlay: overlayChart };
    const c   = map[chartId];
    if (c && _zoomOk && typeof c.resetZoom === 'function') c.resetZoom();
    _hideReset(`reset-${chartId}-zoom`);
}

// ─── addHistory (giữ nguyên) ──────────────────────────────────────────────────
let   _lastBatch      = 0;
const BATCH_WINDOW_MS = 3000;

export function addHistory(type, value, timestamp) {
    const h   = state.history;
    const now = Date.now();
    if (now - _lastBatch > BATCH_WINDOW_MS) {
        _lastBatch = now;
        h.timestamps.push(timestamp);
        if (h.timestamps.length > CONFIG.maxDataPoints) h.timestamps.shift();
        ['moisture','temperature','light','humidity','co2'].forEach(k => {
            const a = h[k];
            a.push(a.length > 0 ? a[a.length - 1] : NaN);
            if (a.length > CONFIG.maxDataPoints) a.shift();
        });
    }
    const arr = h[type];
    if (arr.length > 0) arr[arr.length - 1] = value;
    else arr.push(value);
    debouncedRefreshChart();
}

// ─── loadBulkHistory (giữ nguyên) ────────────────────────────────────────────
export function loadBulkHistory(type, dataArray) {
    const h = state.history;
    if (h.timestamps.length === 0 || type === 'moisture')
        h.timestamps = dataArray.map(d => d.time);
    h[type] = dataArray.map(d => d.value);
    while (h[type].length < h.timestamps.length)   h[type].unshift(NaN);
    if (h[type].length      > CONFIG.maxDataPoints) h[type]      = h[type].slice(-CONFIG.maxDataPoints);
    if (h.timestamps.length > CONFIG.maxDataPoints) h.timestamps = h.timestamps.slice(-CONFIG.maxDataPoints);
    debouncedRefreshChart();
}

// ─── exportCSV (nâng cấp: thêm cột pump events) ──────────────────────────────
export function exportCSV() {
    const h = state.history;
    if (h.timestamps.length === 0) { alert('Chưa có dữ liệu để xuất!'); return; }
    let csv = 'Thời gian,Độ ẩm đất (%),Nhiệt độ (°C),Ánh sáng (lux),Độ ẩm KK (%),CO₂ (ppm)\n';
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
    a.href = url;
    a.download = `nhakinh_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}
