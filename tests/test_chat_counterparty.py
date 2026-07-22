"""Chat wiring TRỤC NHỚ theo-đối-tác: nêu tên đối tác ở tin → nhớ qua các lượt phiên (conv.counterparty
persist) → analyze/negotiate gắn ĐÚNG counterparty → memory-aware review recall 'Về đối tác này'.
Trước đây conv.counterparty là field CHẾT (không persist SQL + analyze/negotiate không truyền)."""
from __future__ import annotations

from legalguard.adapters.inbound.channels import (
    INTENT_NEGOTIATE,
    INTENT_SET_COUNTERPARTY,
    ChatHandler,
    _extract_counterparty,
    _parse_set_counterparty,
    route_intent,
)
from legalguard.adapters.outbound.conversation_store import (
    InMemoryConversationStore,
    SqlAlchemyConversationStore,
)
from legalguard.config.container import build_parser
from legalguard.domain.models import AnalysisResult, Conversation


# ---- Pure extractor -----------------------------------------------------------------------------
def test_extract_counterparty_matches_clear_patterns():
    assert _extract_counterparty("rà hợp đồng với đối tác ACME Corp") == "ACME Corp"
    assert _extract_counterparty("bên bán là Tân Phát") == "Tân Phát"
    assert _extract_counterparty("please review, contract with Globex Ltd") == "Globex Ltd"
    assert _extract_counterparty("với công ty Minh Long về thanh toán") == "Minh Long"


def test_extract_counterparty_rejects_vague():
    assert _extract_counterparty("rà giúp hợp đồng này") == ""
    assert _extract_counterparty("đối tác từ chối đề nghị") == ""   # 'từ chối' không phải tên
    assert _extract_counterparty("họ muốn tăng phạt") == ""
    assert _extract_counterparty("") == ""


# ---- ChatHandler: capture + thread into analyze -------------------------------------------------
class _CapturingService:
    """Ghi lại position mỗi lần analyze → kiểm counterparty được truyền vào."""
    def __init__(self):
        self.positions = []

        class _R:
            available = True

            def complete(self, prompt, *, system=None):   # noqa: ANN001
                return "GIST"
        self.reasoner = _R()

    def analyze(self, text, org, lang="vi", position=None, source=None, on_progress=None, mode="deep"):
        self.positions.append(position)
        return AnalysisResult(tenant="VN", risks=[{"clause": "X", "risk": "r", "severity": "low"}],
                              fallbacks=[], needs_human_review=False, review_reasons=[],
                              summary="s", trace=[], strategy="")


# Đường dùng thực: TẢI FILE HĐ + CAPTION nêu đối tác (attachment → bỏ qua nhánh 'xin rà soát' → ANALYZE).
_CONTRACT_BYTES = ("HỢP ĐỒNG MUA BÁN\nĐiều 1: Bên B chịu phạt vi phạm 15% giá trị hợp đồng.\n"
                   "Điều 2: Tranh chấp giải quyết bằng trọng tài tại Bắc Kinh.").encode("utf-8")


def test_chat_analyze_captures_and_passes_counterparty():
    svc = _CapturingService()
    h = ChatHandler(svc, build_parser(), InMemoryConversationStore(), "VN")
    h.reply("k1", text="rà giúp, với đối tác ACME Corp",
            attachment=_CONTRACT_BYTES, filename="hopdong.txt")
    assert svc.positions and svc.positions[-1] is not None
    assert svc.positions[-1].counterparty == "ACME Corp"
    assert h.store.get("k1").counterparty == "ACME Corp"        # persist trong phiên


def test_chat_counterparty_persists_across_turns():
    svc = _CapturingService()
    h = ChatHandler(svc, build_parser(), InMemoryConversationStore(), "VN")
    h.reply("k2", text="với đối tác ACME Corp", attachment=_CONTRACT_BYTES, filename="a.txt")
    # Lượt sau tải HĐ KHÁC, KHÔNG nhắc tên đối tác → vẫn dùng lại từ phiên.
    h.reply("k2", text="rà giúp cái này", attachment=_CONTRACT_BYTES, filename="b.txt")
    assert svc.positions[-1] is not None
    assert svc.positions[-1].counterparty == "ACME Corp"


# ---- Set/clear counterparty command -------------------------------------------------------------
def test_parse_set_counterparty():
    assert _parse_set_counterparty("đối tác: ACME Corp") == "ACME Corp"
    assert _parse_set_counterparty("đối tác là Tân Phát") == "Tân Phát"
    assert _parse_set_counterparty("đổi đối tác sang Globex Ltd") == "Globex Ltd"
    assert _parse_set_counterparty("counterparty: Minh Long") == "Minh Long"
    assert _parse_set_counterparty("quên đối tác") == ""              # lệnh XÓA
    assert _parse_set_counterparty("xóa đối tác đi") == ""
    assert _parse_set_counterparty("đối tác từ chối đề nghị") is None  # counter-offer, KHÔNG phải lệnh
    assert _parse_set_counterparty("rà giúp hợp đồng này") is None


def test_route_set_counterparty():
    assert route_intent("đối tác: ACME Corp", has_attachment=False, contract_detected=False,
                        has_context=False, has_thread_context=False, in_thread=False,
                        has_prev_review=False, has_last_case=False) == INTENT_SET_COUNTERPARTY
    # 'đối tác từ chối' TRONG deal → đàm phán, KHÔNG bị lệnh set nuốt
    assert route_intent("đối tác từ chối giảm phạt", has_attachment=False, contract_detected=False,
                        has_context=True, has_thread_context=False, in_thread=False,
                        has_prev_review=False, has_last_case=False) == INTENT_NEGOTIATE


def test_chat_set_and_clear_counterparty():
    svc = _CapturingService()
    h = ChatHandler(svc, build_parser(), InMemoryConversationStore(), "VN")
    r = h.reply("k3", text="đối tác: ACME Corp")
    assert "ACME Corp" in r and h.store.get("k3").counterparty == "ACME Corp"
    # rà HĐ sau đó (không nhắc tên) → dùng counterparty đã đặt
    h.reply("k3", text="rà giúp", attachment=_CONTRACT_BYTES, filename="c.txt")
    assert svc.positions[-1].counterparty == "ACME Corp"
    # xóa
    h.reply("k3", text="quên đối tác")
    assert h.store.get("k3").counterparty == ""


# ---- Outcome → counterparty attribution (Option B: derive from case) ----------------------------
def test_record_deal_outcome_attributes_counterparty_from_case():
    from legalguard.adapters.inbound.channels import _record_deal_outcome
    from legalguard.adapters.outbound.memory_store import InMemoryMemory
    from legalguard.domain.analysis import AnalysisService
    from legalguard.domain.models import AnalysisCase

    case = AnalysisCase(id="c9", org_id="org1", tenant="VN", created_at="2026-07-22", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[{"clause": "Phạt vi phạm"}], fallbacks=[], trace=[],
                        counterparty="ACME Corp")

    class _Cases:
        def get(self, cid):   # noqa: ANN001
            return case if cid == "c9" else None

    class _LLM:
        available = False

        def embed(self, t):   # noqa: ANN001
            return None

    mem = InMemoryMemory()
    svc = AnalysisService(reasoner=_LLM(), kb=object(), cases=_Cases(), memory=mem, agentic_memory=True)
    assert _record_deal_outcome(svc, "org1", "c9", "accepted") == 1
    got = svc.recall_memory("org1", "phạt", counterparty="ACME Corp")
    assert got and got[0].kind == "outcome" and got[0].counterparty == "ACME Corp"


# ---- SQL store round-trips the new column -------------------------------------------------------
def test_sql_store_roundtrips_counterparty(tmp_path):
    url = f"sqlite:///{tmp_path / 'conv.db'}"
    conv = Conversation(id="slack:c:t", context="deal", counterparty="ACME Corp")
    SqlAlchemyConversationStore(url).save(conv)
    got = SqlAlchemyConversationStore(url).get("slack:c:t")
    assert got is not None and got.counterparty == "ACME Corp"
