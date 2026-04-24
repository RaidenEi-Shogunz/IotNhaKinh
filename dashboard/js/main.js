/**
 * main.js - Nang cap v4.0
 * ==========================
 * Khoi dong dashboard voi chien luoc dual-source:
 *
 *   1. Thu ket noi Local WebSocket (ws://localhost:8080) truoc
 *   2. Neu co local server -> dung WS push thuan tuy, khong can Adafruit IO
 *   3. Neu khong co local  -> hien Login overlay, dung Adafruit IO MQTT nhu cu
 *   4. Ca 2 nguon co the song song: local WS cap nhat realtime,
 *      MQTT van nhan alert / lenh dieu khien tu dashboard khac
 *
 * Lenh dieu khien (bom, mode, nguong):
 *   - Neu local connected  -> gui qua REST API local (/api/control/...)
 *   - Neu co MQTT          -> gui qua MQTT (backup / remote control)
 */

import { CONFIG, state } from './config.js';
import {
    cacheDOMElements, loadTheme, toggleTheme,
    updatePumpDisplay, updateModeDisplay, startSimClockFallback
} from './uiController.js';
import { initChart, switchChart, exportCSV } from './chartManager.js';
import { connectMQTT, publishMQTT } from './mqttService.js';
import {
    checkLocalServer, connectLocalWS, isLocalConnected,
    sendLocalCommand, LOCAL_API_BASE
} from './localApiService.js';

// ------------------------------------------------------------------
// Inject Local API badge vao header
// ------------------------------------------------------------------
function _injectLocalBadge() {
    const headerRight = document.querySelector('.header-right');
    if (!headerRight || document.getElementById('local-api-status')) return;
    const badge = document.createElement('span');
    badge.id          = 'local-api-status';
    badge.className   = 'local-badge offline';
    badge.title       = 'Local API: dang kiem tra...';
    badge.textContent = '⚡ Local';
    badge.style.cssText = (
        'font-size:0.72rem;padding:3px 8px;border-radius:12px;cursor:default;'
        + 'font-weight:500;letter-spacing:0.02em;margin-right:4px;'
    );
    headerRight.prepend(badge);
}

// ------------------------------------------------------------------
// Login modal
// ------------------------------------------------------------------
function showLoginModal() {
    const loginModal = document.getElementById('login-overlay');
    const overlay    = document.getElementById('connection-overlay');
    if (loginModal) loginModal.classList.remove('hidden');
    if (overlay)    overlay.classList.add('hidden');
}

function hideConnectionOverlay() {
    const overlay = document.getElementById('connection-overlay');
    if (overlay) overlay.classList.add('hidden');
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
            errorMsg.textContent = 'Username Adafruit không hợp lệ!';
            errorMsg.classList.remove('hidden');
        }
        return;
    }

    if (errorMsg) errorMsg.classList.add('hidden');

    sessionStorage.setItem('aio_username', user);
    localStorage.setItem('aio_username', user);
    CONFIG.username = user;
    CONFIG.key      = key;

    const loginModal = document.getElementById('login-overlay');
    if (loginModal) loginModal.classList.add('hidden');
    const overlay = document.getElementById('connection-overlay');
    if (overlay) overlay.classList.remove('hidden');

    connectMQTT();
}

// ------------------------------------------------------------------
// Lenh dieu khien (dual-publish: local API + MQTT fallback)
// ------------------------------------------------------------------
async function togglePump() {
    if (state.currentMode === 'AUTO') return;
    const newState = state.pumpOn ? 'OFF' : 'ON';
    if (isLocalConnected()) {
        const res = await sendLocalCommand('/api/control/pump', { state: newState });
        if (!res.ok) console.warn('[Main] Local pump command that bai:', res.error);
    }
    if (state.connected) publishMQTT(CONFIG.feeds.pumpCmd, newState);
}

async function setMode(mode) {
    if (isLocalConnected()) await sendLocalCommand('/api/control/mode', { mode });
    if (state.connected)    publishMQTT(CONFIG.feeds.mode, mode);
    state.currentMode = mode;
    updateModeDisplay();
}

let _thresholdTimer = null;
async function onThresholdChange(val) {
    val = parseFloat(val);
    if (isNaN(val)) return;
    val = Math.max(10, Math.min(80, Math.round(val)));
    const el = document.getElementById('threshold-value');
    if (el) el.textContent = val + '%';
    clearTimeout(_thresholdTimer);
    _thresholdTimer = setTimeout(async () => {
        if (isLocalConnected()) await sendLocalCommand('/api/control/threshold', { value: val });
        if (state.connected)    publishMQTT(CONFIG.feeds.threshold, val);
    }, 500);
}

// ------------------------------------------------------------------
// Khoi dong chinh
// ------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    cacheDOMElements();
    loadTheme();
    initChart();
    startSimClockFallback(10);
    _injectLocalBadge();

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

    // ================================================================
    // Chien luoc dual-source: Thu local WS truoc
    // ================================================================
    console.log('[Main] Dang kiem tra Local API server...');
    const hasLocal = await checkLocalServer();

    if (hasLocal) {
        console.log(`[Main] Tim thay Local API. Ket noi WebSocket...`);
        hideConnectionOverlay();
        connectLocalWS(() => {}, () => {});

        // Van ket noi MQTT neu co credentials (remote control)
        const savedUser = sessionStorage.getItem('aio_username') || localStorage.getItem('aio_username');
        if (savedUser && CONFIG.key) {
            console.log('[Main] Co credentials -> ket noi MQTT lam backup...');
            connectMQTT();
        } else {
            _showLocalOnlyBanner();
        }
    } else {
        // Fallback sang Adafruit IO nhu cu
        console.log('[Main] Khong co Local API. Dung Adafruit IO MQTT...');
        if (!connectMQTT()) {
            showLoginModal();
        }
    }
});

// ------------------------------------------------------------------
// Banner thong bao khi dang chay Local-only
// ------------------------------------------------------------------
function _showLocalOnlyBanner() {
    const banner = document.createElement('div');
    banner.id    = 'local-only-banner';
    banner.style.cssText = (
        'position:fixed;bottom:16px;right:16px;'
        + 'background:var(--color-background-secondary);'
        + 'border:1px solid var(--color-border-secondary);'
        + 'border-radius:10px;padding:10px 14px;'
        + 'font-size:0.8rem;color:var(--color-text-secondary);'
        + 'max-width:280px;z-index:100;'
        + 'box-shadow:0 2px 8px rgba(0,0,0,0.15);'
    );
    banner.innerHTML = (
        '<b style="color:var(--color-text-primary)">⚡ Chế độ Local</b><br>'
        + 'Đang nhận dữ liệu từ simulator. '
        + 'Không cần Adafruit IO key.<br>'
        + `<a href="${LOCAL_API_BASE}/docs" target="_blank" `
        + 'style="color:var(--color-text-info);text-decoration:none;">'
        + '→ Xem API Docs</a>'
        + '<span id="close-local-banner" style="float:right;cursor:pointer;'
        + 'color:var(--color-text-tertiary);margin-left:8px;">✕</span>'
    );
    document.body.appendChild(banner);
    document.getElementById('close-local-banner')?.addEventListener('click', () => banner.remove());
}
