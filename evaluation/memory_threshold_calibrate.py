"""Calibrate `_MIN_SIM` (noise-floor recall bộ nhớ) trên embedding Qwen THẬT 1024-dim.

Vì sao: `sql_memory_store._MIN_SIM=0.15` là sàn chọn trên EMBEDDER GIẢ (memory_eval). Embedding thật
(Qwen text-embedding-v4) có cosine nền CAO — text KHÔNG liên quan vẫn ~0.3-0.5 → 0.15 quá thấp, lọt nhiễu.
Script này ĐO phân bố cosine RELATED (query ↔ tình tiết cùng chủ đề) vs UNRELATED (khác chủ đề) → gợi ý
ngưỡng tách. Cần QWEN_API_KEY. Không đụng DB/CRDB (chỉ embed + cosine).

Chạy: uv run python -m evaluation.memory_threshold_calibrate
"""
from __future__ import annotations


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# Tình tiết bộ nhớ theo CHỦ ĐỀ (nội dung như _remember_outcome/_remember_negotiation sinh ra) + 1 query
# CÙNG chủ đề mỗi cái. Cross-topic = UNRELATED.
_CASES = [
    ("thanh_toan", "Điều khoản Thanh toán: đối tác ACME đòi phạt chậm thanh toán 15%, ta giữ trần 8% theo Điều 301 → accepted",
     "đối tác này từng đòi mức phạt chậm thanh toán bao nhiêu"),
    ("giao_hang", "Điều khoản Giao hàng: ACME muốn giao hàng trong 30 ngày, ta chốt 45 ngày kèm dung sai → partial",
     "thời hạn giao hàng đã thỏa thuận với đối tác"),
    ("bao_mat", "Điều khoản Bảo mật: NDA ban đầu đơn phương, ta đổi thành bảo mật song phương 2 năm → accepted",
     "điều khoản bảo mật NDA với đối tác trước đây thế nào"),
    ("trong_tai", "Điều khoản Giải quyết tranh chấp: đối tác muốn trọng tài tại Singapore SIAC, ta chốt VIAC Hà Nội → accepted",
     "cơ quan trọng tài đã chốt trong deal trước"),
    ("lai_suat", "Điều khoản Lãi chậm trả: đối tác đề xuất lãi 25%/năm, ta hạ về trần 20% theo Điều 468 BLDS → accepted",
     "mức lãi suất chậm trả từng đàm phán với đối tác"),
    ("shtt", "Điều khoản Sở hữu trí tuệ: quyền tác giả phần mềm giao cho bên đặt hàng, ta giữ quyền nhân thân → partial",
     "thỏa thuận quyền sở hữu trí tuệ với đối tác này"),
]


def run() -> dict:
    from legalguard.config.settings import settings
    from legalguard.adapters.outbound.qwen import QwenAdapter

    llm = QwenAdapter(settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model,
                      embed_model=settings.qwen_embed_model)
    if not llm.available:
        print("Thiếu QWEN_API_KEY — không calibrate được (cần embedding thật).")
        return {}
    ep_texts = [c[1] for c in _CASES]
    q_texts = [c[2] for c in _CASES]
    ep_vecs = llm.embed(ep_texts)
    q_vecs = llm.embed(q_texts)
    if not ep_vecs or not q_vecs:
        print("Embed trả rỗng.")
        return {}
    print(f"dim = {len(ep_vecs[0])}")
    related, unrelated = [], []
    for i, qv in enumerate(q_vecs):
        for j, ev in enumerate(ep_vecs):
            c = _cos(qv, ev)
            (related if i == j else unrelated).append(c)
    rel_min, rel_mean = min(related), sum(related) / len(related)
    unr_max, unr_mean = max(unrelated), sum(unrelated) / len(unrelated)
    # Ngưỡng gợi ý: chính giữa max(unrelated) và min(related) — tách sạch nếu min(related) > max(unrelated).
    gap = rel_min - unr_max
    suggest = round((rel_min + unr_max) / 2, 2)
    print(f"\nRELATED   (query ↔ cùng chủ đề): min={rel_min:.3f} mean={rel_mean:.3f}")
    print(f"UNRELATED (khác chủ đề):         max={unr_max:.3f} mean={unr_mean:.3f}")
    print(f"GAP (min_related - max_unrelated) = {gap:+.3f}")
    if gap > 0:
        print(f"→ TÁCH SẠCH. Ngưỡng _MIN_SIM GỢI Ý ≈ {suggest} (giữa 2 cụm; margin an toàn).")
    else:
        print(f"→ CHỒNG LẤN (gap<0): không tách hoàn toàn bằng 1 ngưỡng. Cân nhắc {suggest} (đổi lấy "
              f"chút recall/precision) + dựa counterparty-boost.")
    print(f"   (Hiện _MIN_SIM=0.15 → so với UNRELATED mean={unr_mean:.3f}: {'QUÁ THẤP, lọt nhiễu' if 0.15 < unr_mean else 'ok'}.)")
    return {"related_min": rel_min, "unrelated_max": unr_max, "gap": gap, "suggest": suggest,
            "related_mean": rel_mean, "unrelated_mean": unr_mean}


if __name__ == "__main__":
    run()
