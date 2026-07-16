from legalguard.adapters.inbound.channels import ChatHandler
from legalguard.adapters.outbound.conversation_store import (
    InMemoryConversationStore,
    RedisConversationStore,
    SqlAlchemyConversationStore,
)
from legalguard.config.container import build_parser
from legalguard.domain.models import AnalysisResult, Conversation


def test_sql_store_persists_across_instances(tmp_path):
    url = f"sqlite:///{tmp_path / 'conv.db'}"
    conv = Conversation(id="zalo:u1", context="đang bàn HĐ trọng tài")
    conv.add("user", "chào")
    conv.add("assistant", "vâng")
    SqlAlchemyConversationStore(url).save(conv)

    # Instance KHÁC, cùng DB (mô phỏng đa instance) → vẫn đọc được phiên.
    got = SqlAlchemyConversationStore(url).get("zalo:u1")
    assert got is not None
    assert got.context == "đang bàn HĐ trọng tài"
    assert len(got.history) == 2


class _FakeRedis:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v, ex=None):
        self.d[k] = v


def test_redis_store_roundtrip():
    store = RedisConversationStore("redis://localhost:6379/0")   # from_url không kết nối ngay
    store.r = _FakeRedis()                                       # thay client để test logic offline
    conv = Conversation(id="zalo:u2", context="HĐ X")
    conv.add("user", "hỏi")
    store.save(conv)
    got = store.get("zalo:u2")
    assert got.context == "HĐ X" and len(got.history) == 1


class _FakeReasoner:
    available = True

    def complete(self, prompt, *, system=None):
        return "GIST"


class _FakeService:
    def __init__(self):
        self.reasoner = _FakeReasoner()

    def analyze(self, text, org, lang="vi", position=None, source=None, on_progress=None, mode="deep"):
        return AnalysisResult(tenant="VN", risks=[{"clause": "X", "risk": "r", "severity": "high",
                              "priority": "must_fix"}], fallbacks=[], needs_human_review=False,
                              review_reasons=[], summary="s", trace=[], strategy="giữ X")


def test_summarization_bounds_history_and_keeps_summary():
    h = ChatHandler(_FakeService(), build_parser(), InMemoryConversationStore(), "VN")
    h.reply("k", text="hợp đồng có điều khoản trọng tài")     # analyze → set context
    for i in range(14):
        h.reply("k", text=f"hỏi tiếp {i}")                    # follow-up
    conv = h.store.get("k")
    assert len(conv.history) <= 12                            # đã gộp lượt cũ, giữ N gần
    assert "[Tóm tắt]" in conv.context                        # tóm tắt tiến hóa được lưu
