"""ĐA-TỔ-CHỨC (review #2): kênh chat resolve org theo workspace (Slack team_id / Zalo OA / web) qua
`channel_org_map`. Map RỖNG → mọi kênh = org 'default' (ĐƠN tổ chức, hành vi hiện tại). Map có → cô lập
dữ liệu/bộ nhớ theo org_id giữa các công ty."""
from __future__ import annotations

from legalguard.adapters.inbound.channels import ChatHandler
from legalguard.adapters.outbound.conversation_store import InMemoryConversationStore
from legalguard.config.container import build_parser
from legalguard.domain.models import AnalysisResult
from legalguard.domain.tenants import resolve_org


# ---- resolver thuần -----------------------------------------------------------------------------
def test_resolve_org_pure():
    assert resolve_org("slack", "T1", {}, "VN").id == "default"              # map rỗng → default
    assert resolve_org("slack", "T1", {"slack:T1": "acme"}).id == "acme"     # map trúng
    assert resolve_org("slack", "T9", {"slack:T1": "acme"}).id == "default"  # workspace lạ → default
    assert resolve_org("slack", "", {"slack:T1": "acme"}).id == "default"    # thiếu workspace → default
    assert resolve_org("zalo", "OA5", {"zalo:OA5": "globex"}).id == "globex" # surface khác
    assert resolve_org("slack", "T1", {"slack:T1": "acme"}, "VN").country == "VN"


# ---- ChatHandler.resolve_org (surface suy từ conversation_id) ------------------------------------
def test_handler_resolve_org_by_surface():
    h = ChatHandler(object(), build_parser(), InMemoryConversationStore(), "VN",
                    org_map={"slack:T1": "acme", "zalo:OA2": "globex"})
    assert h.resolve_org("T1", "slack:C123:ts").id == "acme"
    assert h.resolve_org("OA2", "zalo:u9").id == "globex"
    assert h.resolve_org("T1", "web:uuid").id == "default"   # surface web KHÔNG khớp key slack:
    assert h.resolve_org("", "slack:C:t").id == "default"    # không workspace → default


# ---- e2e: reply_ex(workspace_id) → analyze chạy dưới org đã resolve -----------------------------
class _CapSvc:
    def __init__(self):
        self.orgs = []

        class _R:
            available = True

            def complete(self, p, *, system=None):   # noqa: ANN001
                return "g"
        self.reasoner = _R()

    def analyze(self, text, org, lang="vi", position=None, source=None, on_progress=None, mode="deep"):
        self.orgs.append(org.id)
        return AnalysisResult(tenant="VN", risks=[], fallbacks=[], needs_human_review=False,
                              review_reasons=[], summary="s", trace=[], strategy="")


_C = "HỢP ĐỒNG\nĐiều 1: phạt vi phạm 15%. Trọng tài Bắc Kinh.".encode("utf-8")


def test_chat_analyze_runs_under_resolved_org():
    svc = _CapSvc()
    h = ChatHandler(svc, build_parser(), InMemoryConversationStore(), "VN",
                    org_map={"slack:T1": "acme"})
    # workspace map trúng → org 'acme'
    h.reply_ex("slack:C:t1", text="rà giúp", attachment=_C, filename="a.txt", workspace_id="T1")
    assert svc.orgs[-1] == "acme"
    # workspace lạ → org 'default' (cô lập: không lẫn với acme)
    h.reply_ex("slack:C:t2", text="rà giúp", attachment=_C, filename="b.txt", workspace_id="T9")
    assert svc.orgs[-1] == "default"
