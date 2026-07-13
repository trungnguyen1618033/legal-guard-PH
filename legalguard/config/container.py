"""Composition root: nơi DUY NHẤT lắp adapter vào domain.

Đây là chỗ "ráp hexagon": chọn adapter cụ thể (Qwen, file KB, CSV...) và
tiêm vào các use-case + API. Đổi provider = đổi ở đây, không đụng domain.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from legalguard.adapters.inbound.channels import ChatHandler, build_channels_router
from legalguard.adapters.outbound.chat_senders import SlackSender, ZaloSender
from legalguard.adapters.outbound.conversation_store import (
    InMemoryConversationStore,
    RedisConversationStore,
    SqlAlchemyConversationStore,
)
from legalguard.adapters.inbound.http import build_api
from legalguard.adapters.outbound.document_parser import OcrFallbackParser, PdfDocxParser
from legalguard.adapters.outbound.knowledge_base import FileKnowledgeBaseProvider
from legalguard.adapters.outbound.observability import LangfuseObserver, NoOpObserver
from legalguard.adapters.outbound.qwen import QwenAdapter
from legalguard.adapters.outbound.qwen_vision_ocr import QwenVisionOcr
from legalguard.adapters.outbound.revenue_log import CsvRevenueLog
from legalguard.adapters.outbound.sql_case_repository import SqlAlchemyCaseRepository
from legalguard.adapters.outbound.sql_feedback_repository import SqlAlchemyFeedbackRepository
from legalguard.adapters.outbound.sql_outcome_repository import SqlAlchemyOutcomeRepository
from legalguard.config.settings import Settings, settings
from legalguard.domain.analysis import AnalysisService
from legalguard.domain.evidence import EvidenceService
from legalguard.domain.tenants import Organization


def _parse_orgs(raw: str) -> dict[str, Organization]:
    """ "KEY:ORG_ID:COUNTRY,..." → {api_key: Organization}. """
    out: dict[str, Organization] = {}
    for part in raw.split(","):
        bits = [b.strip() for b in part.split(":")]
        if len(bits) >= 2 and bits[0]:
            country = bits[2].upper() if len(bits) > 2 else "VN"
            out[bits[0]] = Organization(id=bits[1], country=country)
    return out


def build_service(cfg: Settings = settings, kb_strategy: str = "auto") -> AnalysisService:
    reasoner = QwenAdapter(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_model,
                           embed_model=cfg.qwen_embed_model, temperature=cfg.llm_temperature,
                           rerank_model=cfg.qwen_rerank_model)
    # Judge NHANH (qwen-flash) cho việc phụ yes/no (NLI, verify, cổng relevance — DÙNG CẢ /analyze lẫn /lookup)
    # — ~0.5s/call thay vì ~40s flagship, cắt mạnh latency hậu-agent mà không bỏ bước kiểm. judge_temperature=0:
    # yes/no cần TẤT ĐỊNH (abstain/verify không dao động → eval ổn định). Tách khỏi lookup_temperature để chỉnh
    # nhiệt /lookup KHÔNG vô tình đổi hành vi NLI/verify của /analyze. Cùng key/endpoint.
    judge = QwenAdapter(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_fast_model,
                        temperature=cfg.judge_temperature)
    # Model tra cứu (tùy chọn): rỗng = dùng flagship reasoner; đặt qwen-plus để nhanh hơn.
    # temperature=lookup_temperature (0) → câu trả lời tra cứu TẤT ĐỊNH (hết flaky must_say do sampling).
    lookup_llm = (QwenAdapter(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_lookup_model,
                              temperature=cfg.lookup_temperature) if cfg.qwen_lookup_model else None)
    # Point-in-time lookup dùng flagship (suy luận thời điểm) nhưng cũng temp 0 → tất định.
    lookup_pit_llm = QwenAdapter(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_model,
                                 temperature=cfg.lookup_temperature)
    embed_fn = reasoner.embed if reasoner.available else None
    reranker = reasoner if cfg.rerank_enabled else None
    # Cross-encoder rerank: RERANK_URL (self-host TEI, vd AITeamVN) ưu tiên hơn qwen3-rerank API khi được đặt.
    rerank_fn = None
    if cfg.cross_encoder_rerank:
        if cfg.rerank_url:
            from legalguard.adapters.outbound.http_reranker import HttpReranker
            hr = HttpReranker(cfg.rerank_url)
            rerank_fn = hr.rerank if hr.available else None
        elif reasoner.available:
            rerank_fn = reasoner.rerank
    # Embed bền (corpus lớn không re-embed mỗi boot) — opt-in PERSIST_EMBEDDINGS; lưu chung DB.
    embed_store = None
    if cfg.persist_embeddings and embed_fn is not None:
        from legalguard.adapters.outbound.embedding_store import SqlEmbeddingStore
        embed_store = SqlEmbeddingStore(cfg.database_url, enable_ann=cfg.pgvector_ann)
    kb = FileKnowledgeBaseProvider(cfg.knowledge_base_dir, embed_fn=embed_fn,
                                   reranker_llm=reranker, strategy=kb_strategy,
                                   rerank_fn=rerank_fn, closure=cfg.citation_closure,
                                   in_force=cfg.in_force_filter, embed_store=embed_store,
                                   tt_sar=cfg.tt_sar_rerank,
                                   domain_scoped=cfg.domain_scoped_retrieval)
    cases = SqlAlchemyCaseRepository(cfg.database_url)
    outcomes = SqlAlchemyOutcomeRepository(cfg.database_url)
    feedback = SqlAlchemyFeedbackRepository(cfg.database_url)
    observer = (LangfuseObserver(cfg.langfuse_public_key, cfg.langfuse_secret_key, cfg.langfuse_host)
                if cfg.langfuse_secret_key else NoOpObserver())
    return AnalysisService(reasoner=reasoner, kb=kb,
                           cases=cases, outcomes=outcomes, observer=observer,
                           legal_basis_grounding=cfg.legal_basis_grounding, feedback=feedback,
                           nli_verification=cfg.nli_verification, judge=judge,
                           lookup_cache_size=cfg.lookup_cache_size, lookup_llm=lookup_llm,
                           lookup_pit_llm=lookup_pit_llm,
                           illegal_detection=cfg.illegal_detection,
                           coverage_gated_abstain=cfg.coverage_gated_abstain,
                           hyde_query_expansion=cfg.hyde_query_expansion,
                           auto_counter_on_analyze=cfg.auto_counter_on_analyze,
                           auto_counter_max=cfg.auto_counter_max)


def build_evidence(cfg: Settings = settings) -> EvidenceService:
    return EvidenceService(CsvRevenueLog(cfg.revenue_log_path))


def build_conversation_store(cfg: Settings = settings):
    if cfg.conversation_backend == "memory":
        return InMemoryConversationStore()
    if cfg.conversation_backend == "redis" and cfg.redis_url:
        return RedisConversationStore(cfg.redis_url)
    return SqlAlchemyConversationStore(cfg.database_url)


def build_parser(cfg: Settings = settings) -> OcrFallbackParser:
    ocr = QwenVisionOcr(cfg.qwen_api_key, cfg.qwen_base_url, cfg.qwen_vl_model)
    return OcrFallbackParser(PdfDocxParser(), ocr)


def _setup_logging(cfg: Settings) -> None:
    """Cấu hình log cho `legalguard.*` để hiện trong `docker logs` (uvicorn không bật INFO cho app
    logger). Mức theo `LOG_LEVEL` (mặc định INFO → thấy timing analyze, cảnh báo auth, lỗi degrade)."""
    lg = logging.getLogger("legalguard")
    lg.setLevel(cfg.log_level.upper())
    if not lg.handlers:                         # tránh gắn handler trùng khi reload/đa import
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        lg.addHandler(h)
    lg.propagate = False                        # không nhân đôi qua root


def build_app(cfg: Settings = settings) -> FastAPI:
    _setup_logging(cfg)
    service = build_service(cfg)
    parser = build_parser(cfg)
    api_orgs = _parse_orgs(cfg.api_keys)
    if not api_orgs:   # rỗng = MỞ (ai cũng gọi được, chung org 'default') — chỉ hợp dev
        if cfg.require_auth:   # fail-closed: PROD KHÔNG được chạy mở
            raise RuntimeError(
                "API_KEYS rỗng nhưng REQUIRE_AUTH=true — từ chối khởi động ở chế độ MỞ. "
                "Đặt API_KEYS=\"key:org:VN,...\".")
        logging.getLogger("legalguard").warning(
            "⚠️ API_KEYS rỗng — API đang MỞ KHÔNG xác thực (mọi caller chung org 'default'). "
            "PROD đặt REQUIRE_AUTH=true + API_KEYS.")
    # Senders dùng chung: webhook reply + cảnh báo pháp lý chủ động (POST /impact/{id}/notify).
    slack_sender = SlackSender(cfg.slack_bot_token)
    zalo_sender = ZaloSender(cfg.zalo_access_token)
    app = build_api(service, parser, build_evidence(cfg),
                    default_tenant=cfg.default_tenant, api_orgs=api_orgs,
                    max_upload_bytes=cfg.max_upload_bytes, rate_limit_per_min=cfg.rate_limit_per_min,
                    max_input_chars=cfg.max_input_chars,
                    senders={"slack": slack_sender, "zalo": zalo_sender},
                    expert_channel=cfg.expert_channel)
    # Kênh nhắn tin (Zalo/Slack) — chỉ mount webhook khi có secret tương ứng.
    # rank_fn = cross-encoder qwen3-rerank dùng chung với KB retrieval (semantic scoring cho việc
    # CHỌN TIN LIÊN QUAN trong thread nhiều người — M4b); None → builder fallback lexical/recency.
    handler = ChatHandler(service, parser, build_conversation_store(cfg), cfg.default_tenant,
                          rank_fn=getattr(service.kb, "rerank_fn", None))
    app.include_router(build_channels_router(
        handler, slack_signing_secret=cfg.slack_signing_secret,
        zalo_oa_secret=cfg.zalo_oa_secret, zalo_app_id=cfg.zalo_app_id,
        slack_sender=slack_sender,
        zalo_sender=zalo_sender,
        max_upload_bytes=cfg.max_upload_bytes,
        mention_only=cfg.slack_mention_only,
        resolve_names=cfg.slack_resolve_names))
    return app
