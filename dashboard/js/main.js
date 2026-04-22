import { CONFIG, state } from './config.js';
import {
    cacheDOMElements, loadTheme, toggleTheme,
    updatePumpDisplay, updateModeDisplay, startSimClockFallback
} from './uiController.js';
import { initChart, switchChart, exportCSV } from './chartManager.js';
import { connectMQTT, publishMQTT } from './mqttService.js';

function showLoginModal() {
    const loginModal = document.getElementById('login-overlay');
    const overlay    = document.getElementById('connection-overlay');
    if (loginModal) loginModal.classList.remove('hidden');
    if (overlay)    overlay.classList.add('hidden');
}

function handleLogin() {
    const userField = document.getElementById('login-username');
    const keyField  = document.getElementById('login-key');
    const errorMsg  = document.getElementById('login-error');

    const user = userField ? userField.value.trim() : '';
    const key  = keyField  ? keyField.value.trim()  : '';

    if (!user || !key) {
        if (errorMsg) {
            errorMsg.textContent = 'Vui lòng nhập đầy đủ thông tin!';
            errorMsg.classList.remove('hidden');
        }
        return;
    }

    const aioUserRegex = /^[a-z0-9_-]{3,32}$/i;
    if (!aioUserRegex.test(user)) {
        if (errorMsg) {
            errorMsg.textContent = 'Username Adafruit không hợp lệ (chỉ gồm chữ, số, gạch dưới, gạch ngang)!';
            errorMsg.classList.remove('hidden');
        }
        return;
    }

    if (errorMsg) errorMsg.classList.add('hidden');

    // Luu username vao sessionStorage (cong khai), KHONG luu key (bao mat XSS)
    sessionStorage.setItem('aio_username', user);
    CONFIG.username = user;
    CONFIG.key      = key;   // Chi giu trong bo nho, khong ghi ra storage

    const loginModal = document.getElementById('login-overlay');
    if (loginModal) loginModal.classList.add('hidden');
    const overlay = document.getElementById('connection-overlay');
    if (overlay) overlay.classList.remove('hidden');

    const hint = document.getElementById('connection-hint');
    if (hint) {
        hint.textContent = 'Kết nối đến Adafruit IO Broker';
        hint.style.color = '';
    }

    connectMQTT();
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

let thresholdTimer = null;
function onThresholdChange(val) {
    // FIX Thieu Validation: Kiem tra kieu du lieu va clamp gia tri truoc khi publish
    val = parseFloat(val);
    if (isNaN(val)) return;
    val = Math.max(10, Math.min(80, Math.round(val)));
    
    const el = document.getElementById('threshold-value');
    if (el) el.textContent = val + '%';
    clearTimeout(thresholdTimer);
    thresholdTimer = setTimeout(() => {
        publishMQTT(CONFIG.feeds.threshold, val);
    }, 500);
}

document.addEventListener('DOMContentLoaded', () => {
    cacheDOMElements();
    loadTheme();
    initChart();

    if (!connectMQTT()) {
        showLoginModal();
    }

    // Truyen TIME_SCALE vao fallback clock de noi suy chinh xac
    startSimClockFallback(10);

    document.querySelectorAll('.chart-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => switchChart(tab.dataset.chart));
    });

    const btnPump   = document.getElementById('btn-pump');
    const btnAuto   = document.getElementById('btn-auto');
    const btnManual = document.getElementById('btn-manual');
    const slider    = document.getElementById('threshold-slider');
    const btnTheme  = document.getElementById('btn-theme');
    const btnExport = document.getElementById('btn-export');
    const btnLogin  = document.getElementById('btn-login');

    if (btnPump)   btnPump.addEventListener('click', togglePump);
    if (btnAuto)   btnAuto.addEventListener('click', () => setMode('AUTO'));
    if (btnManual) btnManual.addEventListener('click', () => setMode('MANUAL'));
    if (slider)    slider.addEventListener('input', () => onThresholdChange(slider.value));
    if (btnTheme)  btnTheme.addEventListener('click', toggleTheme);
    if (btnExport) btnExport.addEventListener('click', exportCSV);
    if (btnLogin)  btnLogin.addEventListener('click', handleLogin);
});
