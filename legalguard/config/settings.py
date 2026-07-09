"""Cấu hình đọc từ biến môi trường / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Qwen (LLM chính)
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen3.7-max"       # flagship, 1M context, suy luận mạnh nhất (Alibaba gợi ý 6/2026)
    # Model NHANH cho việc phụ đơn giản (NLI yes/no, verify gộp) — ~0.5s/call vs ~40s của flagship.
    # Right-sizing: việc khó (agent phân tích) vẫn dùng qwen_model; việc kiểm tra yes/no dùng model này.
    qwen_fast_model: str = "qwen-flash"
    # Model cho TRA CỨU (lookup Q&A): qwen-plus ~10x nhanh hơn flagship, format/citation y hệt. HYBRID:
    # câu có MỐC THỜI GIAN (point-in-time) tự dùng flagship cho chính xác. Rỗng = luôn flagship.
    qwen_lookup_model: str = "qwen-plus"
    qwen_embed_model: str = "text-embedding-v4"  # Qwen3-Embedding: đa ngữ 100+, #1 MTEB
    qwen_vl_model: str = "qwen3.7-plus"   # multimodal — OCR HĐ scan/ảnh (thay Qwen-VL, chính xác hơn)
    qwen_rerank_model: str = "qwen3-rerank"  # cross-encoder rerank (Model Studio: Qwen-Rerank, 100+ ngôn ngữ)
    llm_temperature: float = 0.1          # thấp = nhất quán/ổn định (legal cần xác định)
    lookup_temperature: float = 0.0       # TRA CỨU (lookup) dùng temp 0 → câu trả lời TẤT ĐỊNH (hết flaky must_say)
    judge_temperature: float = 0.0        # judge (NLI/verify/cổng relevance, DÙNG CẢ /analyze) temp 0 → yes/no tất định; tách khỏi lookup

    # App
    default_tenant: str = "VN"
    knowledge_base_dir: str = "knowledge_base"
    rerank_enabled: bool = False     # bật LLM rerank (tốn thêm call); mặc định dùng hybrid RRF
    cross_encoder_rerank: bool = False  # bật cross-encoder rerank (Qwen qwen3-rerank) — ưu tiên hơn LLM rerank
    rerank_url: str = ""             # base URL reranker self-host (TEI /rerank, vd AITeamVN); rỗng = dùng qwen3-rerank API
    citation_closure: bool = False   # bật citation closure: đi theo dẫn chiếu kéo về điều luật liên quan (Phase 2)
    tt_sar_rerank: bool = False      # TT-SAR: rerank đồ-thị theo cạnh typed+temporal (arXiv:2604.06173 mở rộng); opt-in, đo A/B trước khi bật prod
    in_force_filter: bool = True     # mặc định CHỈ trả văn bản còn hiệu lực (lọc theo front-matter status)
    persist_embeddings: bool = False  # lưu embedding bền trong DB (chỉ embed chunk mới) → mở khóa corpus lớn
    pgvector_ann: bool = True         # dùng pgvector ANN nếu DB Postgres có extension (tự phát hiện); False = ép brute-force
    domain_scoped_retrieval: bool = True   # định tuyến truy vấn theo lĩnh vực (chống cạnh-tranh-toàn-cục khi KB lớn) — ĐÃ qua gate 9/7: accuracy 53→54/54, sửa ca "phạt vi phạm thương mại" bị PDPD Đ.8 (phạt hành chính) nuốt; đặt env=0 để tắt
    legal_basis_grounding: bool = True  # gắn căn cứ điều luật (tất định, từ KB) cho mỗi risk/fallback
    nli_verification: bool = True       # kiểm entailment: nguồn có hậu thuẫn claim không (chống hallucinate; tốn thêm LLM call)
    coverage_gated_abstain: bool = True  # cổng relevance quyết trên cụm evidence tập trung (elbow) → chống over-abstain lookup
    hyde_query_expansion: bool = False   # HyDE-lite: LLM sinh thuật ngữ luật cầu nối query↔luật → retrieval chặt hơn (opt-in, +1 call/lookup)
    illegal_detection: bool = True      # Phase B: NLI-mâu-thuẫn nâng unfavorable→illegal khi trái điều luật đã grounding
    lookup_cache_size: int = 256        # cache câu trả lời tra cứu (hỏi lặp → trả tức thì + tiết kiệm token); 0 = tắt
    slack_mention_only: bool = True     # Slack: CHỈ trả lời khi được mention (@bot) hoặc DM — không mention = user đang nói với người khác, bot im lặng; =0 khôi phục hành vi cũ (trả lời mọi tin)
    slack_resolve_names: bool = True    # Slack: resolve TÊN THẬT người nói trong thread (users.info, scope users:read) cho attribution ai-nói-gì; =0 → nhãn ẩn danh Người A/B/C (thân tin vẫn redact PII như cũ)

    # Chat session store: sql (persist + đa instance) | memory (dev) | redis
    conversation_backend: str = "sql"
    redis_url: str = ""              # redis://host:6379/0 (local) | rediss://... (TLS/Upstash)

    # Bảo mật. api_keys dạng "KEY:ORG_ID:COUNTRY" (vd "k1:acme:VN,k2:globex:VN").
    # → bật auth + cô lập theo công ty (org). Rỗng = mở (chỉ dev).
    api_keys: str = ""
    require_auth: bool = False         # PROD đặt true → từ chối khởi động nếu API_KEYS rỗng (fail-closed)
    max_upload_bytes: int = 10 * 1024 * 1024   # 10MB
    max_input_chars: int = 50_000      # trần độ dài text/câu hỏi gửi LLM (chống abuse chi phí)
    rate_limit_per_min: int = 60               # 0 = tắt; in-process (prod nên dùng Redis)

    # Observability (Langfuse — rỗng = NoOp)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # Kênh nhắn tin (rỗng = tắt webhook tương ứng)
    slack_signing_secret: str = ""
    slack_bot_token: str = ""        # gửi reply Slack (chat.postMessage) + tải file
    zalo_oa_secret: str = ""
    zalo_app_id: str = ""
    expert_channel: str = ""         # kênh Slack chuyên gia pháp lý nhận case escalation (Reject/illegal)
    zalo_access_token: str = ""      # gửi reply Zalo OA + tải ảnh
    revenue_log_path: str = "data/revenue.csv"
    # SQLite cho local/dev; prod đổi sang postgresql+psycopg://user:pass@host:5432/legalguard
    database_url: str = "sqlite:///data/cases.db"
    # Mức log của app (DEBUG/INFO/WARNING). INFO → thấy timing analyze + cảnh báo trong `docker logs`.
    log_level: str = "INFO"


settings = Settings()
