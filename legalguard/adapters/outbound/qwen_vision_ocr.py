"""OCR bằng Qwen-VL (DashScope, tương thích OpenAI) → implement OcrPort.

Ảnh (.jpg/.png) → gửi thẳng base64. PDF scan → render từng trang bằng pymupdf rồi OCR.
Đúng hệ sinh thái Qwen Cloud (ăn điểm "dùng sâu Qwen"). Không key → available=False.
"""
from __future__ import annotations

import base64

from legalguard.adapters.outbound._http import post_json

_MAX_PDF_PAGES = 5   # giới hạn để bound chi phí token
_PROMPT = "Trích xuất TOÀN BỘ văn bản trong ảnh hợp đồng này, giữ nguyên, không diễn giải."


class QwenVisionOcr:
    name = "qwen-vl"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def ocr(self, data: bytes, filename: str) -> str:
        name = filename.lower()
        if name.endswith(".pdf"):
            images = _pdf_to_pngs(data)
            mime = "image/png"
        else:
            images = [data]
            mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"
        return "\n".join(self._ocr_image(img, mime) for img in images).strip()

    def _ocr_image(self, img: bytes, mime: str) -> str:
        b64 = base64.b64encode(img).decode()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
        }
        data = post_json(f"{self.base_url}/chat/completions", provider=self.name,
                         headers={"Authorization": f"Bearer {self.api_key}"},
                         json=payload, timeout=120)
        return data["choices"][0]["message"]["content"]


def _pdf_to_pngs(data: bytes) -> list[bytes]:
    import pymupdf  # lazy

    doc = pymupdf.open(stream=data, filetype="pdf")
    out = []
    for page in list(doc)[:_MAX_PDF_PAGES]:
        out.append(page.get_pixmap(dpi=150).tobytes("png"))
    return out
