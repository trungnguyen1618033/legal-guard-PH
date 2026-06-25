"""Composition root: nơi DUY NHẤT lắp adapter vào domain.

Đây là chỗ "ráp hexagon": chọn adapter cụ thể (Qwen, Gemini, file KB, CSV...) và
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
from legalguard.adapters.outbound.gemini import GeminiAdapter
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
    summarizer = GeminiAdapter(cfg.gemini_api_key, cfg.gemini_model, temperature=cfg.llm_temperature)
    embed_fn = reasoner.embed if reasoner.available else None
    reranker = reasoner if cfg.rerank_enabled else None
    rerank_fn = reasoner.rerank if (cfg.cross_encoder_rerank and reasoner.available) else None
    kb = FileKnowledgeBaseProvider(cfg.knowledge_base_dir, embed_fn=embed_fn,
                                   reranker_llm=reranker, strategy=kb_strategy,
                                   rerank_fn=rerank_fn, closure=cfg.citation_closure,
                                   in_force=cfg.in_force_filter)
    cases = SqlAlchemyCaseRepository(cfg.database_url)
    outcomes = SqlAlchemyOutcomeRepository(cfg.database_url)
    feedback = SqlAlchemyFeedbackRepository(cfg.database_url)
    observer = (LangfuseObserver(cfg.langfuse_public_key, cfg.langfuse_secret_key, cfg.langfuse_host)
                if cfg.langfuse_secret_key else NoOpObserver())
    return AnalysisService(reasoner=reasoner, summarizer=summarizer, kb=kb,
                           cases=cases, outcomes=outcomes, observer=observer,
                           legal_basis_grounding=cfg.legal_basis_grounding, feedback=feedback,
                           nli_verification=cfg.nli_verification)


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


def build_app(cfg: Settings = settings) -> FastAPI:
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
    app = build_api(service, parser, build_evidence(cfg),
                    default_tenant=cfg.default_tenant, api_orgs=api_orgs,
                    max_upload_bytes=cfg.max_upload_bytes, rate_limit_per_min=cfg.rate_limit_per_min,
                    max_input_chars=cfg.max_input_chars)
    # Kênh nhắn tin (Zalo/Slack) — chỉ mount webhook khi có secret tương ứng.
    handler = ChatHandler(service, parser, build_conversation_store(cfg), cfg.default_tenant)
    app.include_router(build_channels_router(
        handler, slack_signing_secret=cfg.slack_signing_secret,
        zalo_oa_secret=cfg.zalo_oa_secret, zalo_app_id=cfg.zalo_app_id,
        slack_sender=SlackSender(cfg.slack_bot_token),
        zalo_sender=ZaloSender(cfg.zalo_access_token),
        max_upload_bytes=cfg.max_upload_bytes))
    return app
