/**
 * ══════════════════════════════════════════════════════════════
 * LEAF GATE — Stage 1: MobileNet (ImageNet) + Green Ratio
 * ══════════════════════════════════════════════════════════════
 * Xác định ảnh có phải lá cây / thực vật không TRƯỚC KHI
 * chạy Teachable Machine (Stage 2).
 *
 * Hai kiểm tra song song:
 *   [A] MobileNet ImageNet: top-5 predictions có chứa class
 *       liên quan thực vật không (leaf, plant, flower, herb...)
 *   [B] Green Ratio: tỉ lệ pixel xanh lá trong ảnh (HSV filter)
 *
 * Kết quả:  PASS  — ít nhất 1 check pass → cho qua Stage 2
 *           BLOCK — cả 2 đều fail → chặn, báo rõ lý do
 *
 * Tham khảo:
 *   - MobileNet v2: Sandler et al. 2018
 *   - ImageNet class list: 1000 classes (ILSVRC2012)
 * ══════════════════════════════════════════════════════════════
 */

// ── ImageNet classes liên quan thực vật / nông nghiệp ──
const PLANT_KEYWORDS = [
    // Lá cây, thực vật chung
    'leaf', 'plant', 'flower', 'tree', 'herb', 'grass', 'moss', 'fern',
    'vine', 'shrub', 'bush', 'seedling', 'sprout',
    // Rau củ quả (ImageNet có nhiều class này)
    'cabbage', 'lettuce', 'broccoli', 'cauliflower', 'cucumber',
    'zucchini', 'squash', 'pumpkin', 'artichoke', 'cardoon',
    'mushroom', 'agaric', 'bolete', 'stinkhorn', 'earthstar',
    'corn', 'ear', 'rapeseed', 'hay',
    // Hoa
    'daisy', 'sunflower', 'rose', 'tulip', 'orchid', 'lily',
    'poppy', 'dandelion', 'bouquet', 'floral',
    // Trái cây
    'banana', 'orange', 'lemon', 'fig', 'pineapple', 'strawberry',
    'apple', 'pomegranate', 'jackfruit', 'custard apple', 'grape',
    // Cảnh quan có cây
    'garden', 'greenhouse', 'pot', 'flowerpot', 'vase',
    'lawn', 'park', 'meadow', 'lakeside',
    // Côn trùng trên cây (vẫn liên quan nông nghiệp)
    'bee', 'butterfly', 'ladybug', 'dragonfly', 'caterpillar',
    'beetle', 'cricket', 'grasshopper', 'mantis',
    // Nấm bệnh
    'fungus', 'lichen', 'coral fungus',
    // Đất, nông nghiệp
    'soil', 'compost', 'hay', 'straw',
];

// ── Cấu hình ──
const GATE_CONFIG = {
    // MobileNet
    MOBILENET_VERSION: 2,
    MOBILENET_ALPHA: 0.5,       // Nhẹ hơn (0.5 thay vì 1.0), tải nhanh
    MOBILENET_TOP_K: 5,         // Kiểm tra top 5 predictions
    MOBILENET_MIN_CONF: 0.05,   // Ngưỡng tối thiểu cho class thực vật

    // Green Ratio (HSV filter)
    GREEN_H_MIN: 35,            // Hue min (green range in HSV)
    GREEN_H_MAX: 155,           // Hue max
    GREEN_S_MIN: 20,            // Saturation min (tránh xám/trắng)
    GREEN_V_MIN: 30,            // Value min (tránh đen)
    GREEN_RATIO_THRESHOLD: 0.08, // 8% pixel xanh → có cây

    // Debounce cho camera mode (tránh chạy MobileNet mỗi frame)
    CAM_GATE_INTERVAL_MS: 2000,  // Chạy gate mỗi 2 giây
    CAM_GATE_CACHE_MS: 5000,     // Cache kết quả 5 giây
};

// ── State ──
let mobilenetModel = null;
let mobileNetLoading = false;
let lastGateResult = null;
let lastGateTime = 0;

/**
 * Load MobileNet model (lazy, chỉ load 1 lần).
 * Sử dụng mobilenet package từ TF.js.
 */
async function loadMobileNet() {
    if (mobilenetModel) return mobilenetModel;
    if (mobileNetLoading) {
        // Đợi model đang load xong
        while (mobileNetLoading) {
            await new Promise(r => setTimeout(r, 100));
        }
        return mobilenetModel;
    }

    mobileNetLoading = true;
    console.log('[LeafGate] Loading MobileNet v2 (alpha=0.5)...');

    try {
        mobilenetModel = await mobilenet.load({
            version: GATE_CONFIG.MOBILENET_VERSION,
            alpha: GATE_CONFIG.MOBILENET_ALPHA,
        });
        console.log('[LeafGate] MobileNet loaded OK');
        return mobilenetModel;
    } catch (err) {
        console.error('[LeafGate] MobileNet load failed:', err);
        throw err;
    } finally {
        mobileNetLoading = false;
    }
}

/**
 * [Check A] MobileNet ImageNet classification.
 * Trả về { pass, topClass, topConf, plantClasses, allPreds }
 */
async function checkMobileNet(imageElement) {
    const net = await loadMobileNet();
    const predictions = await net.classify(imageElement, GATE_CONFIG.MOBILENET_TOP_K);

    let plantClasses = [];
    for (const pred of predictions) {
        const name = pred.className.toLowerCase();
        const isPlant = PLANT_KEYWORDS.some(kw => name.includes(kw));
        if (isPlant && pred.probability >= GATE_CONFIG.MOBILENET_MIN_CONF) {
            plantClasses.push({
                className: pred.className,
                probability: pred.probability,
            });
        }
    }

    const topPred = predictions[0] || { className: 'unknown', probability: 0 };
    return {
        pass: plantClasses.length > 0,
        topClass: topPred.className,
        topConf: topPred.probability,
        plantClasses,
        allPreds: predictions,
    };
}

/**
 * [Check B] Green Ratio — phân tích tỉ lệ pixel xanh lá.
 * Dùng canvas để đọc pixel, chuyển RGB→HSV, đếm pixel trong vùng green.
 * Trả về { pass, ratio, totalPixels, greenPixels }
 */
function checkGreenRatio(imageElement) {
    // Tạo canvas tạm để đọc pixel
    const canvas = document.createElement('canvas');
    const MAX_DIM = 200; // Resize nhỏ để tính nhanh
    let w = imageElement.width || imageElement.videoWidth || 224;
    let h = imageElement.height || imageElement.videoHeight || 224;

    // Nếu là canvas (webcam), lấy kích thước canvas
    if (imageElement instanceof HTMLCanvasElement) {
        w = imageElement.width;
        h = imageElement.height;
    }

    // Scale down
    const scale = Math.min(MAX_DIM / w, MAX_DIM / h, 1.0);
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);

    const ctx = canvas.getContext('2d');
    ctx.drawImage(imageElement, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    const totalPixels = canvas.width * canvas.height;
    let greenPixels = 0;

    for (let i = 0; i < data.length; i += 4) {
        const r = data[i], g = data[i + 1], b = data[i + 2];

        // RGB → HSV
        const hsv = rgbToHsv(r, g, b);

        // Check green range
        if (hsv.h >= GATE_CONFIG.GREEN_H_MIN &&
            hsv.h <= GATE_CONFIG.GREEN_H_MAX &&
            hsv.s >= GATE_CONFIG.GREEN_S_MIN &&
            hsv.v >= GATE_CONFIG.GREEN_V_MIN) {
            greenPixels++;
        }
    }

    const ratio = greenPixels / totalPixels;
    return {
        pass: ratio >= GATE_CONFIG.GREEN_RATIO_THRESHOLD,
        ratio,
        totalPixels,
        greenPixels,
        percent: (ratio * 100).toFixed(1),
    };
}

/**
 * RGB → HSV conversion.
 * H: 0-360, S: 0-100, V: 0-100
 */
function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const d = max - min;
    let h = 0, s = max === 0 ? 0 : (d / max) * 100, v = max * 100;

    if (d !== 0) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;

    return { h, s, v };
}

/**
 * ═══════════════════════════════════════════
 * MAIN GATE FUNCTION — chạy cả 2 check
 * ═══════════════════════════════════════════
 *
 * @param {HTMLElement} imageElement - img, video, hoặc canvas
 * @param {string} mode - 'camera' | 'image'
 * @returns {Object} gate result
 *   {
 *     pass: boolean,
 *     mobilenet: { pass, topClass, topConf, plantClasses, allPreds },
 *     greenRatio: { pass, ratio, percent },
 *     reason: string (nếu block),
 *     summary: string (tóm tắt kết quả)
 *   }
 */
async function runLeafGate(imageElement, mode = 'image') {
    // Camera mode: debounce + cache
    if (mode === 'camera') {
        const now = Date.now();
        if (lastGateResult && (now - lastGateTime) < GATE_CONFIG.CAM_GATE_CACHE_MS) {
            return lastGateResult;
        }
    }

    // [B] Green Ratio — chạy trước (nhanh, synchronous)
    const green = checkGreenRatio(imageElement);

    // [A] MobileNet — chạy sau (async, cần GPU/CPU)
    let mnet;
    try {
        mnet = await checkMobileNet(imageElement);
    } catch (err) {
        console.warn('[LeafGate] MobileNet error, fallback to green ratio only:', err);
        mnet = { pass: false, topClass: 'error', topConf: 0, plantClasses: [], allPreds: [] };
    }

    // ── Quyết định Gate ──
    const pass = mnet.pass || green.pass;

    let reason = '';
    let summary = '';

    if (pass) {
        const parts = [];
        if (mnet.pass) {
            const cls = mnet.plantClasses[0];
            parts.push(`MobileNet: "${cls.className}" (${(cls.probability * 100).toFixed(0)}%)`);
        }
        if (green.pass) {
            parts.push(`Green Ratio: ${green.percent}%`);
        }
        summary = `✅ Leaf Gate PASS — ${parts.join(' + ')}`;
    } else {
        reason = `MobileNet nhận diện "${mnet.topClass}" (${(mnet.topConf * 100).toFixed(0)}%) — không phải thực vật. ` +
                 `Tỉ lệ xanh lá: ${green.percent}% (cần ≥${(GATE_CONFIG.GREEN_RATIO_THRESHOLD * 100).toFixed(0)}%).`;
        summary = `🚫 Leaf Gate BLOCK — Không phải ảnh cây trồng`;
    }

    const result = { pass, mobilenet: mnet, greenRatio: green, reason, summary };

    // Cache cho camera mode
    lastGateResult = result;
    lastGateTime = Date.now();

    return result;
}

/**
 * Reset cache (khi chuyển ảnh mới hoặc đổi mode).
 */
function resetGateCache() {
    lastGateResult = null;
    lastGateTime = 0;
}

/**
 * Check if MobileNet is loaded.
 */
function isMobileNetLoaded() {
    return mobilenetModel !== null;
}

// ── Export cho global scope (vì không dùng ES modules) ──
window.LeafGate = {
    run: runLeafGate,
    loadMobileNet,
    checkMobileNet,
    checkGreenRatio,
    resetCache: resetGateCache,
    isLoaded: isMobileNetLoaded,
    CONFIG: GATE_CONFIG,
};
