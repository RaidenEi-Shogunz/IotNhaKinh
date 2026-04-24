/**
 * ══════════════════════════════════════════════════════════════
 * GEMINI VISION — Stage 3: Phân tích sâu với Google Gemini 1.5
 * ══════════════════════════════════════════════════════════════
 * Gửi ảnh chụp tới backend proxy `/api/gemini` để phân tích
 * chuyên sâu. Gemini sẽ trả về JSON chứa khuyến nghị chăm sóc.
 * ══════════════════════════════════════════════════════════════
 */

const GeminiVision = {
    /**
     * Chuyển đổi image/video/canvas thành chuỗi Base64 JPEG.
     * Resize ảnh nhỏ lại (max width/height 800px) để giảm token / bandwidth.
     */
    captureBase64(sourceElement) {
        const MAX_DIM = 800;
        let w = sourceElement.width || sourceElement.videoWidth || sourceElement.naturalWidth || 640;
        let h = sourceElement.height || sourceElement.videoHeight || sourceElement.naturalHeight || 480;

        // Nếu source là canvas (ví dụ: từ webcam)
        if (sourceElement instanceof HTMLCanvasElement) {
            w = sourceElement.width;
            h = sourceElement.height;
        }

        const scale = Math.min(MAX_DIM / w, MAX_DIM / h, 1.0);
        const targetW = Math.round(w * scale);
        const targetH = Math.round(h * scale);

        const canvas = document.createElement('canvas');
        canvas.width = targetW;
        canvas.height = targetH;

        const ctx = canvas.getContext('2d');
        ctx.drawImage(sourceElement, 0, 0, targetW, targetH);

        // Quality 0.8 để giảm dung lượng
        return canvas.toDataURL('image/jpeg', 0.8);
    },

    /**
     * Gọi API phân tích ảnh qua proxy.
     * @param {HTMLElement} sourceElement Ảnh hoặc canvas
     * @param {string} apiKey Google Gemini API Key
     * @param {string} tmClass Kết quả nhận diện từ Stage 2 (để truyền làm context)
     */
    async analyze(sourceElement, apiKey, tmClass = "") {
        if (!apiKey) {
            throw new Error("Vui lòng cấu hình Gemini API Key trong phần Cấu Hình Hệ Thống.");
        }

        const base64Image = this.captureBase64(sourceElement);

        const prompt = `Bạn là một chuyên gia nông nghiệp thông minh (AI Agronomist) đang giám sát một nhà kính IoT.
Đây là hình ảnh cây trồng vừa được camera chụp lại.
Hệ thống AI nhận diện sơ bộ (Stage 2) đánh giá đây là: "${tmClass}".

Vui lòng phân tích hình ảnh này thật kỹ và trả lời bằng JSON theo định dạng sau (không giải thích thêm, chỉ xuất JSON hợp lệ):
{
    "status": "Tình trạng sức khỏe chung của cây (Tốt, Cảnh báo, Nguy hiểm)",
    "observations": [
        "Quan sát chi tiết 1 (ví dụ: màu sắc lá, đốm bệnh, độ héo)",
        "Quan sát chi tiết 2"
    ],
    "disease_pest": "Phát hiện sâu bệnh cụ thể nào không? (Nếu không, ghi 'Không phát hiện')",
    "water_advice": "Khuyến nghị về tưới tiêu (tăng, giảm, giữ nguyên) dựa trên quan sát",
    "general_advice": "Lời khuyên tổng quát để cải thiện tình trạng cây"
}`;

        try {
            // Strip the base64 prefix "data:image/jpeg;base64,"
            const base64Data = base64Image.split(',')[1];
            const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;

            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{
                        parts: [
                            { text: prompt },
                            {
                                inlineData: {
                                    mimeType: "image/jpeg",
                                    data: base64Data
                                }
                            }
                        ]
                    }]
                })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.error?.message || `HTTP Error ${res.status}`);
            }

            const data = await res.json();

            // Lấy nội dung text từ response của Gemini
            if (data.candidates && data.candidates.length > 0 && data.candidates[0].content && data.candidates[0].content.parts.length > 0) {
                const text = data.candidates[0].content.parts[0].text;
                try {
                    // Cố gắng parse JSON từ text (có thể API Gemini trả về dạng Markdown ```json ... ```)
                    let jsonStr = text;
                    if (jsonStr.includes("```json")) {
                        jsonStr = jsonStr.split("```json")[1].split("```")[0].trim();
                    } else if (jsonStr.includes("```")) {
                        jsonStr = jsonStr.split("```")[1].split("```")[0].trim();
                    }
                    return JSON.parse(jsonStr);
                } catch (e) {
                    // Fallback nếu không parse được JSON
                    return {
                        error: "Gemini không trả về định dạng JSON hợp lệ.",
                        raw_text: text
                    };
                }
            } else {
                throw new Error("Không nhận được nội dung phân tích từ Gemini.");
            }
        } catch (err) {
            console.error("[GeminiVision] Error:", err);
            throw err;
        }
    }
};

window.GeminiVision = GeminiVision;
