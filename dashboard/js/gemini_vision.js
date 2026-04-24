/**
 * ══════════════════════════════════════════════════════════════
 * GEMINI VISION — VIP Pro AI Agronomist
 * ══════════════════════════════════════════════════════════════
 */

const GeminiVision = {
    captureBase64(sourceElement) {
        const MAX_DIM = 1024;
        let w = sourceElement.width || sourceElement.videoWidth || sourceElement.naturalWidth || 640;
        let h = sourceElement.height || sourceElement.videoHeight || sourceElement.naturalHeight || 480;

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
        return canvas.toDataURL('image/jpeg', 0.85);
    },

    async analyze(sourceElement, apiKey, tmClass = "", sensorData = null) {
        if (!apiKey) {
            throw new Error("Vui lòng cấu hình Gemini API Key.");
        }

        const base64Image = this.captureBase64(sourceElement);

        let sensorContext = "Không có dữ liệu cảm biến thời gian thực.";
        if (sensorData) {
            sensorContext = `
[Dữ liệu cảm biến môi trường hiện tại]
- Nhiệt độ: ${sensorData.temperature || '--'} °C
- Độ ẩm không khí: ${sensorData.humidity || '--'} %
- Độ ẩm đất: ${sensorData.soil_moisture || '--'} %
- Ánh sáng: ${sensorData.light_intensity || '--'} lux
- Nồng độ CO2: ${sensorData.co2_level || '--'} ppm
- Độ dẫn điện (EC): ${sensorData.ec_level || '--'} mS/cm
- Độ pH: ${sensorData.ph_level || '--'}
`;
        }

        const prompt = `Bạn là một CHUYÊN GIA NÔNG NGHIỆP THÔNG MINH (VIP Pro AI Agronomist) đẳng cấp quốc tế, đang quản lý hệ thống Nhà Kính Sinh Thái Công Nghệ Cao.
Nhiệm vụ của bạn là kết hợp DỮ LIỆU CẢM BIẾN THỜI GIAN THỰC và HÌNH ẢNH CAMERA để đưa ra báo cáo chẩn đoán chính xác nhất.

${sensorContext}

Hệ thống AI nhận diện sơ bộ qua hình ảnh đánh giá đây là: "${tmClass}".
Dựa vào hình ảnh đính kèm và các thông số kỹ thuật bên trên (nếu có), hãy cung cấp báo cáo chuyên sâu. Phân tích sự tương quan giữa thông số môi trường và biểu hiện trên lá/thân cây.

Trả về duy nhất dữ liệu JSON nguyên bản theo cấu trúc sau, không kèm Markdown hay giải thích:
{
    "status": "[Ngắn gọn] Tình trạng sức khỏe chung (Rất Tốt, Tốt, Cần Lưu Ý, Nguy Hiểm)",
    "observations": [
        "Phân tích thị giác 1 (Màu sắc, hình thái lá, tổn thương...)",
        "Phân tích tương quan môi trường (Ví dụ: Độ ẩm đất thấp đang gây héo lá...)"
    ],
    "disease_pest": "[Chi tiết] Tên sâu bệnh/nấm nếu có. Đánh giá mức độ rủi ro.",
    "water_advice": "[Hành động] Điều chỉnh chiến lược tưới tiêu và dinh dưỡng (EC/pH).",
    "general_advice": "[Hành động] Điều chỉnh môi trường (Nhiệt, Sáng, CO2) để tối ưu quang hợp."
}`;

        try {
            const base64Data = base64Image.split(',')[1];
            const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;

            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{
                        parts: [
                            { text: prompt },
                            { inlineData: { mimeType: "image/jpeg", data: base64Data } }
                        ]
                    }]
                })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.error?.message || `HTTP Error ${res.status}`);
            }

            const data = await res.json();
            if (data.candidates && data.candidates[0].content?.parts.length > 0) {
                let text = data.candidates[0].content.parts[0].text;
                let jsonStr = text.replace(/\`\`\`json/g, '').replace(/\`\`\`/g, '').trim();
                return JSON.parse(jsonStr);
            } else {
                throw new Error("Không nhận được nội dung phân tích từ AI.");
            }
        } catch (err) {
            console.error("[GeminiVision] Error:", err);
            throw err;
        }
    }
};

window.GeminiVision = GeminiVision;
