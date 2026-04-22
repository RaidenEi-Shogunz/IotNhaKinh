import { CONFIG, state, DOM } from './config.js';
import { debounce } from './utils.js';

let sensorChart = null;
let moistureChart = null; // FIX: Bieu do do am doc lap

const chartConfigs = {
    moisture:    { label: 'Do am dat (%)',  color: '#3b82f6', min: 0,   max: 100 },
    temperature: { label: 'Nhiet do (C)',   color: '#ef4444', min: 0,   max: 50  },
    light:       { label: 'Anh sang (lux)', color: '#f59e0b', min: 0,   max: 12000 },
    humidity:    { label: 'Do am KK (%)',   color: '#06b6d4', min: 0,   max: 100 },
    co2:         { label: 'CO2 (ppm)',      color: '#8b5cf6', min: 200, max: 1200 },
};

export function initChart(forceRecreate = false) {
    if (forceRecreate) {
        if (sensorChart) { sensorChart.destroy(); sensorChart = null; }
        if (moistureChart) { moistureChart.destroy(); moistureChart = null; }
    }
    
    const canvas = document.getElementById('sensor-chart');
    const canvasMoisture = document.getElementById('moisture-chart');
    if (!canvas || !canvasMoisture) return;
    
    const ctx = canvas.getContext('2d');
    const ctxM = canvasMoisture.getContext('2d');

    const isDark    = document.documentElement.getAttribute('data-theme') !== 'light';
    const tickColor = isDark ? '#94a3b8' : '#475569';
    const gridColor = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';

    // Bieu do phu
    const cfg = chartConfigs[state.activeChart];
    sensorChart = createChartInstance(ctx, cfg, tickColor, gridColor);
    
    // Bieu do do am (co dinh)
    const cfgM = chartConfigs['moisture'];
    moistureChart = createChartInstance(ctxM, cfgM, tickColor, gridColor);
}

function createChartInstance(ctx, cfg, tickColor, gridColor) {
    return new Chart(ctx, {
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
                    title: { display: true, text: cfg.label, color: tickColor, font: { size: 11, weight: 'bold' } },
                    ticks: { color: tickColor, font: { size: 10 } },
                    grid:  { color: gridColor },
                },
            },
        },
    });
}

export function refreshChart() {
    if (!sensorChart || !moistureChart) return;
    const h    = state.history;

    // Update main chart (Moisture)
    moistureChart.data.labels           = [...h.timestamps];
    moistureChart.data.datasets[0].data = [...h.moisture];
    moistureChart.update('none');

    // Update secondary chart
    const type = state.activeChart;
    const cfg  = chartConfigs[type];

    sensorChart.data.labels                       = [...h.timestamps];
    sensorChart.data.datasets[0].data             = [...h[type]];
    sensorChart.data.datasets[0].label            = cfg.label;
    sensorChart.data.datasets[0].borderColor      = cfg.color;
    sensorChart.data.datasets[0].backgroundColor  = cfg.color + '20';
    sensorChart.options.scales.y.min              = cfg.min;
    sensorChart.options.scales.y.max              = cfg.max;
    if (sensorChart.options.scales.y.title) {
        sensorChart.options.scales.y.title.text   = cfg.label;
    }
    sensorChart.update('none');

    // Hide skeleton when data arrives
    const skeleton = document.getElementById('chart-skeleton');
    const canvas = document.getElementById('sensor-chart');
    if (skeleton && skeleton.style.display !== 'none') {
        skeleton.style.display = 'none';
        if (canvas) canvas.style.display = 'block';
    }
    
    const mSkeleton = document.getElementById('moisture-skeleton');
    const mCanvas = document.getElementById('moisture-chart');
    if (mSkeleton && mSkeleton.style.display !== 'none') {
        mSkeleton.style.display = 'none';
        if (mCanvas) mCanvas.style.display = 'block';
    }
}

export const debouncedRefreshChart = debounce(refreshChart, 100);

export function switchChart(type) {
    state.activeChart = type;
    DOM.chartTabs.forEach(t => {
        t.classList.toggle('active', t.dataset.chart === type);
    });
    refreshChart();
}

let lastBatchMs       = 0;
const BATCH_WINDOW_MS = 3000;

export function addHistory(type, value, timestamp) {
    const h   = state.history;
    const now = Date.now();

    if (now - lastBatchMs > BATCH_WINDOW_MS) {
        lastBatchMs = now;
        h.timestamps.push(timestamp);
        if (h.timestamps.length > CONFIG.maxDataPoints) h.timestamps.shift();

        ['moisture', 'temperature', 'light', 'humidity', 'co2'].forEach(key => {
            const arr = h[key];
            // Push the last known value (or NaN if none) to maintain continuity without drawing lines to 0
            arr.push(arr.length > 0 ? arr[arr.length - 1] : NaN);
            if (arr.length > CONFIG.maxDataPoints) arr.shift();
        });
    }

    // Overwrite the most recent data point for this specific sensor type
    const arr = h[type];
    if (arr.length > 0) {
        arr[arr.length - 1] = value;
    } else {
        arr.push(value);
    }
    
    debouncedRefreshChart();
}

export function exportCSV() {
    const h = state.history;
    if (h.timestamps.length === 0) { alert('Chưa có dữ liệu để xuất!'); return; }
    let csv = 'Thời gian,Độ ẩm đất (%),Nhiệt độ (C),Ánh sáng (lux),Độ ẩm KK (%),CO2 (ppm)\n';
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

// FIX: Ham load lich su hang loat de tranh loi batching window
export function loadBulkHistory(type, dataArray) {
    const h = state.history;
    
    // Dung moisture de set timestamp (hoac neu chua co timestamp)
    if (h.timestamps.length === 0 || type === 'moisture') {
        h.timestamps = dataArray.map(d => d.time);
    }
    
    h[type] = dataArray.map(d => d.value);
    
    // Pad array voi NaN neu bi thieu do lech tich tac
    while(h[type].length < h.timestamps.length) {
        h[type].unshift(NaN);
    }
    
    if (h[type].length > CONFIG.maxDataPoints) {
        h[type] = h[type].slice(-CONFIG.maxDataPoints);
    }
    if (h.timestamps.length > CONFIG.maxDataPoints) {
        h.timestamps = h.timestamps.slice(-CONFIG.maxDataPoints);
    }
    
    debouncedRefreshChart();
}
