import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from legalguard.adapters.inbound.channels import (
    ChatHandler,
    _mrkdwn_blocks,
    build_channels_router,
    format_chat_reply,
)
from legalguard.adapters.outbound.conversation_store import InMemoryConversationStore
from legalguard.config.container import build_parser, build_service
from legalguard.domain.models import AnalysisResult


def _handler():
    return ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")

MSG = "Tranh chấp bằng trọng tài tại Bắc Kinh."


class _FakeSender:
    def __init__(self, available=True, file_bytes=b"", thread_msgs=None):
        self._a = available
        self.sent = []
        self.threads = []
        self.downloaded = []
        self.fetched = []                  # các (channel, thread_ts) đã fetch_thread
        self._fb = file_bytes
        self._tm = thread_msgs or []

    @property
    def available(self):
        return self._a

    def send(self, conv, text, thread_ts=None, blocks=None):
        self.sent.append((conv, text))
        self.threads.append(thread_ts)
        self.blocks = blocks
        return "111.222"                   # ts giả (cho phép chat.update heartbeat)

    def update(self, conv, ts, text, blocks=None):
        self.updated = getattr(self, "updated", [])
        self.updated.append((conv, ts, text))

    def upload_file(self, conv, filename, data, thread_ts=None, title="", comment=""):
        self.uploaded = getattr(self, "uploaded", [])
        self.uploaded.append((conv, filename, len(data), thread_ts))
        return True

    def download(self, url):
        self.downloaded.append(url)
        return self._fb

    def fetch_thread(self, channel, thread_ts):
        self.fetched.append((channel, thread_ts))
        return self._tm

    def resolve_names(self, user_ids):
        return {}                      # mặc định không resolve — builder dùng nhãn ẩn danh


def _client(slack="", zalo="", appid="", slack_sender=None, zalo_sender=None, mention_only=False):
    # mention_only=False mặc định trong TEST: các test routing/flow cũ gửi event không mention
    # (legacy mode vẫn phải chạy đúng — flag tắt được trên prod). Gate test riêng bật True.
    handler = _handler()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret=slack,
                                             zalo_oa_secret=zalo, zalo_app_id=appid,
                                             slack_sender=slack_sender, zalo_sender=zalo_sender,
                                             mention_only=mention_only))
    return TestClient(app)


def _slack_post(client, secret, payload):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))      # timestamp tươi (qua replay check)
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/channels/slack/events", content=body,
                       headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})


# ---- format / handler ----
def test_format_chat_reply():
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Trọng tài", "risk": "Bất lợi",
                         "severity": "high", "priority": "must_fix"}], fallbacks=[],
                         needs_human_review=True, review_reasons=[], summary="", trace=[],
                         strategy="Giữ điều khoản trọng tài")
    out = format_chat_reply(res)
    # Văn xuôi pháp lý: đánh số (1), 'Tại điều khoản …', KHÔNG icon màu, KHÔNG nhãn ưu tiên.
    assert "(1) Tại điều khoản “Trọng tài”: Bất lợi" in out and "Giữ điều khoản trọng tài" in out
    assert "🔴" not in out and "🟠" not in out and "📋" not in out and "must_fix" not in out


def test_format_chat_reply_appends_drafting_notes():
    # Lỗi soạn thảo → ĐÁNH SỐ TIẾP TỤC sau rủi ro (không còn tiêu đề 'Lỗi soạn thảo' riêng).
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Đ1", "risk": "x", "severity": "low"}],
                         fallbacks=[], needs_human_review=False, review_reasons=[], summary="",
                         trace=[], strategy="",
                         drafting_notes=["Tại Điều 3, gõ nhầm; đề xuất sửa thành: PHÁT TRIỂN"])
    out = format_chat_reply(res)
    assert "(1) Tại điều khoản “Đ1”" in out and "(2) Tại Điều 3" in out and "PHÁT TRIỂN" in out
    # không có drafting_notes → không có mục (2)
    res2 = AnalysisResult(tenant="VN", risks=[{"clause": "Đ1", "risk": "x", "severity": "low"}],
                          fallbacks=[], needs_human_review=False, review_reasons=[], summary="",
                          trace=[], strategy="")
    assert "(2)" not in format_chat_reply(res2)


def test_analysis_blocks_include_drafting_section():
    from legalguard.adapters.inbound.channels import _analysis_blocks
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Đ1", "risk": "x"}], fallbacks=[],
                         needs_human_review=False, review_reasons=[], summary="", trace=[],
                         drafting_notes=["Tại Điều 7, sai chính tả; đề xuất sửa thành: abc"])
    dump = json.dumps(_analysis_blocks(res, "c1"), ensure_ascii=False)
    assert "(2) Tại Điều 7" in dump and "abc" in dump      # số tiếp sau rủi ro (1)


def test_review_head_empty_findings_no_contradiction():
    # Không có rủi ro/lỗi → KHÔNG nói 'đề xuất điều chỉnh' rồi 'không phát hiện' (mâu thuẫn).
    from legalguard.adapters.inbound.channels import _analysis_blocks
    res = AnalysisResult(tenant="VN", risks=[], fallbacks=[], needs_human_review=False,
                         review_reasons=[], summary="", trace=[], contract_type="HĐ vay")
    out = format_chat_reply(res)
    assert "không phát hiện" in out and "đề xuất điều chỉnh một số nội dung" not in out
    dump = json.dumps(_analysis_blocks(res, "c1"), ensure_ascii=False)
    assert "không phát hiện" in dump and "đề xuất điều chỉnh một số nội dung" not in dump


def test_drafting_segments_continuous_numbering_skips_empty():
    # Note rỗng KHÔNG tạo lỗ hổng số thứ tự (đánh số theo vị trí hiển thị).
    from legalguard.adapters.inbound.channels import _drafting_segments
    res = AnalysisResult(tenant="VN", risks=[{"clause": "A", "risk": "b"}], fallbacks=[],
                         needs_human_review=False, review_reasons=[], summary="", trace=[],
                         drafting_notes=["", "Tại Điều 2, lỗi; đề xuất sửa thành: X", "  "])
    segs = _drafting_segments(res, start_num=2)             # 1 rủi ro → drafting bắt đầu (2)
    # fallback drafting_notes (không cấu trúc) → (num, text, dclause="" → KHÔNG nút)
    assert segs == [(2, "(2) Tại Điều 2, lỗi; đề xuất sửa thành: X", "")]


def test_drafting_issues_structured_render_card_and_button():
    # Lỗi soạn thảo CÓ CẤU TRÚC → thẻ nhãn-đậm + nút 'Đồng ý sửa' (giống risk); Slack slackify **→*.
    import json as _j

    from legalguard.adapters.inbound.channels import _analysis_blocks, _drafting_segments
    res = AnalysisResult(tenant="VN", risks=[{"clause": "A", "risk": "b"}], fallbacks=[],
                         needs_human_review=False, review_reasons=[], summary="", trace=[],
                         drafting_issues=[{"location": "Điều 1.2 bản EN", "issue": "sai tên LIN",
                                           "fix_vi": "Sửa thành LIN HSUAN", "fix_en": "Change to LIN HSUAN"}])
    num, seg, dclause = _drafting_segments(res, start_num=2)[0]
    assert num == 2 and dclause == "Điều 1.2 bản EN"
    assert "**(2) Lỗi soạn thảo tại" in seg and "**Tiếng Việt:**" in seg and "**Tiếng Anh:**" in seg
    blocks = _analysis_blocks(res, "case1")
    vals = [_j.loads(el["value"]) for b in blocks if b["type"] == "actions" for el in b["elements"]]
    assert any(v.get("dc") == "Điều 1.2 bản EN" and v.get("confirm") == 1 for v in vals)  # nút drafting (actions block dưới)
    assert "**" not in _j.dumps(blocks, ensure_ascii=False)                               # đã slackify


def test_comment_items_from_case_includes_drafting():
    # File Word có comment gồm CẢ lỗi soạn thảo (không chỉ rủi ro): location→clause, issue→risk, fix→vi/en.
    from types import SimpleNamespace

    from legalguard.adapters.inbound.channels import _comment_items_from_case
    case = SimpleNamespace(
        risks=[{"clause": "Điều 5", "evidence": "phạt 15%", "risk": "vượt trần",
                "counter_clause": {"vi": "8%"}, "legal_status": "illegal", "violated_law": "Đ.301"}],
        fallbacks=[],
        drafting_issues=[{"location": "Điều 1.2 EN", "issue": "sai tên LIN",
                          "fix_vi": "LIN HSUAN", "fix_en": "LIN HSUAN"}])
    items = _comment_items_from_case(case)
    assert len(items) == 2 and items[0]["clause"] == "Điều 5"                 # rủi ro trước
    assert items[1]["clause"] == "Lỗi soạn thảo tại Điều 1.2 EN"              # drafting sau
    assert items[1]["risk"] == "sai tên LIN" and items[1]["vi"] == "LIN HSUAN"


def test_case_roundtrips_drafting_issues():
    # drafting_issues persist + nạp lại (save→get) — cần cho xuất file comment ở lượt chat sau.
    import uuid

    from legalguard.adapters.outbound.sql_case_repository import SqlAlchemyCaseRepository
    from legalguard.domain.models import AnalysisCase
    repo = SqlAlchemyCaseRepository("sqlite://")           # in-memory: create_all + round-trip
    cid = uuid.uuid4().hex
    repo.save(AnalysisCase(id=cid, org_id="o1", tenant="VN", created_at="t", lang="vi",
                           contract_excerpt="", summary="", needs_human_review=False,
                           risks=[], fallbacks=[], trace=[],
                           drafting_issues=[{"location": "Đ.1", "issue": "x", "fix_vi": "y", "fix_en": ""}]))
    got = repo.get(cid)
    assert got is not None and got.drafting_issues == [{"location": "Đ.1", "issue": "x", "fix_vi": "y", "fix_en": ""}]


def test_mark_button_agreed_swaps_only_clicked():
    # Bấm 'Đồng ý sửa' → actions block ĐÃ BẤM thành context '*Đã đồng ý sửa*'; nút khác giữ nguyên; không icon.
    from legalguard.adapters.inbound.channels import _mark_button_agreed
    blocks = [
        {"type": "section", "block_id": "lg_amend_1", "text": {"type": "mrkdwn", "text": "(1)"}},
        {"type": "actions", "block_id": "lg_amend_1_act", "elements": [{"type": "button", "action_id": "amend_ok"}]},
        {"type": "actions", "block_id": "lg_amend_2_act", "elements": [{"type": "button", "action_id": "amend_ok"}]},
    ]
    out = _mark_button_agreed(blocks, "lg_amend_1_act")
    assert out[1]["type"] == "section" and "Đã đồng ý sửa" in out[1]["text"]["text"]   # section nổi bật
    assert "✅" in out[1]["text"]["text"] and "**" not in out[1]["text"]["text"]        # ✅ xanh, không rò `**`
    assert out[2]["type"] == "actions"                    # nút mục khác GIỮ nguyên
    assert _mark_button_agreed(blocks, "nope") is None    # không khớp → None (caller giữ tin)
    assert _mark_button_agreed(blocks, "") is None


def test_confirm_drafting_fix_records_without_llm():
    from legalguard.adapters.inbound.channels import _confirm_drafting_fix

    class _Svc:
        def __init__(self):
            self.outcomes = []

        def record_outcome(self, o):
            self.outcomes.append(o)

    svc, s = _Svc(), _FakeSender()
    _confirm_drafting_fix(svc, s, "default", "c1", "Điều 1.2 bản EN", "C1", "th")
    assert len(svc.outcomes) == 1 and svc.outcomes[0].result == "agreed_fix"
    assert svc.outcomes[0].clause == "Điều 1.2 bản EN"
    assert "soạn thảo" in s.sent[-1][1].lower() and s.threads[-1] == "th"


def test_format_chat_reply_marks_illegal():
    # Điều khoản trái luật → diễn đạt PHÁP LÝ (không icon ⚖️): "dấu hiệu trái quy định tại <điều>… vô hiệu".
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Phạt 15%", "risk": "vượt trần",
                         "severity": "high", "priority": "must_fix",
                         "legal_status": "illegal", "violated_law": "Điều 301 LTM 2005"}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "trái quy định tại Điều 301" in out and "vô hiệu" in out and "⚖️" not in out


def test_format_chat_reply_illegal_without_violated_law():
    # illegal thiếu violated_law → "trái quy định của pháp luật" (không 'tại Điều …'), không lỗi chuỗi.
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Điều X", "risk": "trái luật",
                         "severity": "high", "priority": "must_fix",
                         "legal_status": "illegal", "violated_law": ""}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "trái quy định của pháp luật" in out and "tại Điều" not in out


def test_format_chat_reply_unfavorable_not_marked_illegal():
    # điều khoản chỉ bất lợi → KHÔNG bị quy trái luật nhầm.
    res = AnalysisResult(tenant="VN", risks=[{"clause": "Điều Y", "risk": "bất lợi",
                         "severity": "medium", "priority": "negotiate",
                         "legal_status": "unfavorable", "violated_law": ""}],
                         fallbacks=[], needs_human_review=False, review_reasons=[],
                         summary="", trace=[], strategy="")
    out = format_chat_reply(res)
    assert "trái quy định" not in out


def test_format_chat_reply_first_line_client_and_contract_type():
    # Dòng đầu nêu loại HĐ + khách hàng bảo vệ (khi LLM xác định được).
    res = AnalysisResult(tenant="VN", risks=[{"clause": "A", "risk": "b"}], fallbacks=[],
                         needs_human_review=False, review_reasons=[], summary="", trace=[],
                         contract_type="hợp đồng hợp tác đầu tư", protected_party="Công ty CP Du lịch Phú Quốc")
    out = format_chat_reply(res)
    assert out.startswith("Sau khi rà soát hợp đồng hợp tác đầu tư")
    assert "Công ty CP Du lịch Phú Quốc" in out and "đề xuất điều chỉnh một số nội dung sau:" in out


def test_handler_empty_prompts_for_input():
    assert "Gửi giúp" in _handler().reply("c1", text="")


def test_handler_analyzes_text():
    assert "Điều khoản trọng tài" in _handler().reply("c1", text=MSG)


def test_handler_legal_lookup_without_contract():
    # Câu hỏi pháp lý đứng một mình (không tín hiệu HĐ, chưa có deal) → tra cứu KB có grounding,
    # KHÔNG trả câu nhắc chung "Gửi giúp...".
    out = _handler().reply("cL", text="Thời điểm lập hóa đơn khi bán hàng hóa quy định ra sao?")
    assert out and "Gửi giúp" not in out


def test_handler_skips_lookup_for_casual_message():
    # Lời chào/ack vu vơ KHÔNG kích hoạt tra cứu (tránh tốn LLM) → trả câu nhắc nhẹ.
    out = _handler().reply("cZ", text="cảm ơn nhé")
    assert "Gửi giúp" in out


def test_legal_question_in_deal_routes_lookup():
    # Câu hỏi pháp lý CHUNG dù đang trong deal (đã analyze) → LOOKUP (template+nguồn), không follow-up.
    h = _handler()
    h.reply("cDeal", text=MSG)                          # analyze → set context
    assert h.store.get("cDeal").context                  # context đã set
    r = h.reply_ex("cDeal", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?")
    assert r.kind == "lookup"                            # câu pháp lý chung → lookup (nhất quán template)


def test_deal_specific_question_routes_followup():
    # Câu ĐẶC-THÙ-DEAL (không thuật ngữ luật chung) → follow-up theo ngữ cảnh, không lookup.
    h = _handler()
    h.reply("cDeal2", text=MSG)
    r = h.reply_ex("cDeal2", text="Nếu đối tác từ chối thì mình nên làm gì?")
    assert r.kind == ""                                  # follow-up (ChatReply không gắn kind)


def test_legal_question_in_thread_routes_followup_not_lookup():
    # MENTION GIỮA THREAD (in_thread=True) + có deal context → câu GIỐNG tra cứu luật vẫn trả lời THEO
    # NGỮ CẢNH thread (followup), KHÔNG rơi xuống lookup KB chung (fix "mention trong thread → hiểu bối cảnh").
    h = _handler()
    h.reply("cThr", text=MSG)                            # analyze → set context
    # Cùng câu hỏi mà ở DM (test trên) đi LOOKUP → trong thread phải đi FOLLOWUP:
    r = h.reply_ex("cThr", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?", in_thread=True)
    assert r.kind == ""                                  # followup theo ngữ cảnh, KHÔNG phải lookup


def test_help_query_not_shown_mid_deal():
    # BUG user báo: upload file → hỏi (analyze) → HỎI LẠI thì bot trả bảng HELP thay vì trả lời tiếp.
    # Đang trong deal (conv.context đã set) → 'help me…' là hỏi tiếp → followup, KHÔNG phải bảng hướng dẫn.
    h = _handler()
    h.reply("cHelpDeal", text=MSG)                       # analyze → conv.context set
    r = h.reply_ex("cHelpDeal", text="help me understand this better")
    assert "HƯỚNG DẪN" not in r.text                    # không nuốt thành bảng hướng dẫn
    assert r.kind == ""                                  # đi followup theo deal context


def test_help_query_still_shown_when_fresh():
    # Không có deal/thread → 'help' vẫn ra bảng hướng dẫn (không regress).
    assert "HƯỚNG DẪN" in _handler().reply("cHelpFresh", text="help")


def test_review_request_without_file_prompts_to_attach():
    # BUG user báo: gõ 'review this contract' KHÔNG kèm file → bot followup mơ hồ (không nút). Nay hướng
    # dẫn ĐÍNH KÈM lại file (HĐ không lưu đầy đủ nên không tự rà lại được).
    h = _handler()
    r = h.reply_ex("cRev", text="help me to review this contract for Phu Quoc side")
    assert "đính kèm" in r.text.lower() and "hợp đồng" in r.text.lower()
    assert r.kind == ""


def test_wants_whole_contract_review_detector():
    from legalguard.adapters.inbound.channels import _wants_whole_contract_review
    assert _wants_whole_contract_review("help me to review this contract for Phu Quoc side")
    assert _wants_whole_contract_review("rà soát hợp đồng này giúp tôi")
    assert not _wants_whole_contract_review("phân tích điều khoản thanh toán này")  # 1 điều khoản → followup
    assert not _wants_whole_contract_review("Mức phạt tối đa bao nhiêu %?")          # câu hỏi luật


def test_latest_contract_file_picks_most_recent():
    from legalguard.adapters.inbound.channels import _latest_contract_file
    msgs = [
        {"ts": "1", "files": [{"url": "u_old", "name": "contract_v1.docx"}]},
        {"ts": "2", "text": "chat", "files": []},
        {"ts": "3", "files": [{"url": "u_new", "name": "contract_v2.pdf"}]},
        {"ts": "4", "text": "@bot review this contract", "files": []},
    ]
    assert _latest_contract_file(msgs) == ("u_new", "contract_v2.pdf")     # file HĐ GẦN NHẤT
    # không có file loại tài liệu → (None, None)
    assert _latest_contract_file([{"files": [{"url": "u", "name": "pic.gif"}]}]) == (None, None)


def test_latest_contract_file_skips_bot_and_prefers_doc():
    from legalguard.adapters.inbound.channels import _latest_contract_file
    msgs = [
        {"ts": "1", "files": [{"url": "u_doc", "name": "hopdong.pdf"}]},            # tài liệu (user)
        {"ts": "2", "bot_id": "B1", "files": [{"url": "u_bot", "name": "memo.docx"}]},  # BOT → bỏ
        {"ts": "3", "files": [{"url": "u_img", "name": "screenshot.png"}]},         # ảnh mới hơn
    ]
    assert _latest_contract_file(msgs) == ("u_doc", "hopdong.pdf")          # ưu tiên tài liệu user, bỏ file bot


def test_review_request_mid_deal_not_prompt_to_attach():
    # Fix bug: 'review ... contract' NGẮN giữa deal → KHÔNG chặn thành prompt-đính-kèm (để followup trả lời).
    h = _handler()
    h.reply("cRevDeal", text=MSG)                        # analyze → conv.context set
    r = h.reply_ex("cRevDeal", text="re-review the payment clause of the contract")
    assert "đính kèm" not in r.text.lower()              # KHÔNG phải prompt-đính-kèm (đang trong deal)


def test_process_reuses_contract_file_from_thread():
    # User yêu cầu rà soát KHÔNG kèm file; thread có file HĐ ở tin trước → _process dùng file đó → rà soát
    # (KHÔNG hỏi đính kèm lại). Fix cho phản ánh: 'không biết trong thread có file nào không'.
    from legalguard.adapters.inbound.channels import _process
    thread = [{"user": "U1", "text": "hợp đồng đây", "ts": "1",
               "files": [{"url": "u_doc", "name": "hopdong.txt"}]}]
    s = _FakeSender(file_bytes=b"HOP DONG: phat vi pham 15%; thanh toan 90 ngay.", thread_msgs=thread)
    _process(_handler(), s, "slack:C1:100", "C1",
             "help me to review this contract for Phu Quoc side", None, None, "100",
             supports_buttons=True, thread_fetch=("C1", "100"))
    assert "u_doc" in s.downloaded                          # đã tải file HĐ trong thread
    joined = " ".join(t for _, t in s.sent)
    assert "ĐÍNH KÈM" not in joined                         # KHÔNG hỏi đính kèm nữa (đã dùng file thread)


def test_md_to_slack_converts_bold_and_headers():
    # Slack dùng 1 dấu * cho đậm; **x** không render. Chuyển **x**→*x*, tiêu đề #→*…*.
    from legalguard.adapters.inbound.channels import _md_to_slack
    assert _md_to_slack("**Trả lời:** nội dung") == "*Trả lời:* nội dung"
    assert _md_to_slack("## Căn cứ\nĐiều 5") == "*Căn cứ*\nĐiều 5"
    assert "**" not in _md_to_slack("**A** và **B**")     # không còn dấu ** thô
    assert _md_to_slack("*đậm sẵn*") == "*đậm sẵn*"        # đã đúng Slack → giữ nguyên
    assert _md_to_slack("") == "" and _md_to_slack("thường") == "thường"


def test_mrkdwn_blocks_slackifies_bold():
    from legalguard.adapters.inbound.channels import _mrkdwn_blocks
    dump = json.dumps(_mrkdwn_blocks("**Trả lời:** A\n**Căn cứ:** Điều 5"), ensure_ascii=False)
    assert "**" not in dump and "*Trả lời:*" in dump


def test_analysis_blocks_slackifies_bold_in_strategy():
    from legalguard.adapters.inbound.channels import _analysis_blocks
    res = AnalysisResult(tenant="VN", risks=[], fallbacks=[], needs_human_review=False,
                         review_reasons=[], summary="", trace=[], strategy="**Giữ:** điều 5")
    dump = json.dumps(_analysis_blocks(res, "c1"), ensure_ascii=False)
    assert "**" not in dump and "*Giữ:*" in dump


def test_process_slackifies_kindless_reply_on_slack():
    # Hồi quy: reply KHÔNG có kind (reformat/followup/help) → _process không build blocks → PHẢI vẫn qua
    # _md_to_slack, nếu không markdown **đậm** do LLM sinh rò ra Slack dạng chữ (bug user báo:
    # "mấy cái dấu sao này là in đậm mà lỗi ạ?").
    from legalguard.adapters.inbound.channels import ChatReply, _process

    class _H:
        def reply_ex(self, key, **kw):
            return ChatReply("**(1) Sai sót:** cần sửa", "")   # kind rỗng (như _reformat/_followup)

    s = _FakeSender()
    _process(_H(), s, "k", "C1", "viết lại dãn dòng", None, None, "th",
             10 * 1024 * 1024, True)                            # supports_buttons=True = Slack
    sent = " ".join(t for _, t in s.sent)
    assert "**" not in sent and "*(1) Sai sót:*" in sent        # đã slackify, không rò ** thô


def test_process_keeps_plain_text_for_zalo():
    # Zalo (supports_buttons=False) KHÔNG slackify — giữ nguyên (Zalo không dùng cú pháp Slack).
    from legalguard.adapters.inbound.channels import ChatReply, _process

    class _H:
        def reply_ex(self, key, **kw):
            return ChatReply("**đậm**", "")

    s = _FakeSender()
    _process(_H(), s, "k", "U1", "câu hỏi", None, None, None, 10 * 1024 * 1024, False)
    assert any("**đậm**" == t for _, t in s.sent)               # nguyên văn (không đụng)


def _has_emoji(s: str) -> bool:
    import re as _re
    return bool(_re.search(r"[\U0001F000-\U0001FAFF☀-➿⚖✅⚡⭐]", s or ""))


def test_chat_reply_bodies_have_no_icons():
    # User yêu cầu: tin chat BỎ HẲN icon (giữ nhãn nút + file .docx riêng). Khóa: reply rà soát (kể cả
    # cảnh báo rà-nhanh) + công bố độ tin cậy KHÔNG chứa emoji.
    from legalguard.domain.trust import format_trust_text
    res = AnalysisResult(
        tenant="VN", risks=[{"clause": "Điều 5", "risk": "phạt 15%", "evidence": "phạt 15%",
                             "priority": "must_fix", "legal_status": "unfavorable"}],
        fallbacks=[], needs_human_review=True, review_reasons=["nhanh"], summary="", trace=[],
        strategy="Giữ trần 8%.",
        notes=["Bản RÀ NHANH (1-lượt, nông hơn rà Sâu) — có thể BỎ SÓT điều khoản/trái luật; "
               "luật sư cần đối chiếu bản gốc."])
    reply = format_chat_reply(res, lang="vi")
    assert "RÀ NHANH" in reply and not _has_emoji(reply)     # cảnh báo còn text, sạch icon
    assert not _has_emoji(format_trust_text())               # công bố độ tin cậy sạch icon


def test_review_bold_labels_per_channel():
    # Nhãn IN ĐẬM: Slack render `*đậm*` (từ `**`→`*` qua slackify); text/Zalo GỠ sạch dấu (không lộ `**`).
    import json as _json

    from legalguard.adapters.inbound.channels import _analysis_blocks
    res = AnalysisResult(
        tenant="VN", contract_type="hợp đồng mua bán", protected_party="Bên B",
        risks=[{"clause": "Điều 5", "risk": "phạt 15%", "evidence": "Bên B chịu phạt 15%",
                "priority": "must_fix", "legal_status": "illegal", "violated_law": "Điều 301",
                "counter_clause": {"vi": "tối đa 8%", "en": "max 8%", "rationale": "Đ.301"}}],
        fallbacks=[], needs_human_review=True, review_reasons=[], summary="", trace=[], strategy="")
    text = format_chat_reply(res, lang="vi")
    assert "**" not in text and "Nội dung hiện tại:" in text and "Căn cứ:" in text   # text: sạch dấu
    slack = _json.dumps(_analysis_blocks(res, "c1"), ensure_ascii=False)
    assert "**" not in slack and "*Nội dung hiện tại:*" in slack and "*Căn cứ:*" in slack   # Slack: đậm


def test_wants_file_export_intent():
    from legalguard.adapters.inbound.channels import _wants_file_export
    assert _wants_file_export("thêm mục comment vào tệp này")       # phản ánh thật của user
    assert _wants_file_export("cho tôi file word có nhận xét")
    assert _wants_file_export("xuất file docx giúp tôi")
    assert _wants_file_export("tải bản word")
    assert _wants_file_export("add comments to the file")
    assert not _wants_file_export("mức phạt vi phạm hợp đồng là bao nhiêu?")   # câu hỏi thường
    assert not _wants_file_export("rà soát giúp hợp đồng này")                 # yêu cầu rà soát


def test_comment_to_docx_has_word_comments():
    import io
    import zipfile

    from legalguard.adapters.outbound.docx_export import comment_to_docx
    data = comment_to_docx({"items": [
        {"clause": "Điều 5", "evidence": "Bên B chịu phạt 15%", "risk": "vượt trần 8%",
         "legal_status": "illegal", "violated_law": "Điều 301", "vi": "giảm về 8%",
         "en": "reduce to 8%", "rationale": "Điều 301 LTM 2005"}], "protected_party": "Bên B"})
    assert data[:2] == b"PK"                              # docx = zip package
    z = zipfile.ZipFile(io.BytesIO(data))
    assert any("comments" in n for n in z.namelist())    # có comment thật (comments.xml)


def test_export_command_routes_to_export_doc():
    from legalguard.domain.models import Conversation
    h = _handler()
    h.store.save(Conversation(id="kExp", context="deal đang bàn", last_case_id="case-xyz"))
    r = h.reply_ex("kExp", text="cho tôi file word có nhận xét")
    assert r.kind == "export_doc" and r.ref == "case-xyz"    # KHÔNG rà soát lại — trả file


def test_export_command_without_case_gives_guidance():
    from legalguard.domain.models import Conversation
    h = _handler()
    h.store.save(Conversation(id="kExp2", context="deal"))    # chưa có last_case_id
    r = h.reply_ex("kExp2", text="xuất file word cho tôi")
    assert r.kind == "" and "chưa có kết quả rà soát" in r.text.lower()


def test_process_export_doc_uploads_commented_docx():
    from types import SimpleNamespace

    from legalguard.adapters.inbound.channels import ChatReply, _process
    from legalguard.domain.tenants import default_org
    org = default_org("VN")
    case = SimpleNamespace(
        org_id=org.id, protected_party="Bên B", contract_type="mua bán",
        risks=[{"clause": "Điều 5", "evidence": "phạt 15%", "risk": "vượt trần 8%",
                "legal_status": "illegal", "violated_law": "Điều 301",
                "counter_clause": {"vi": "giảm 8%", "en": "8%", "rationale": "Đ.301"}}],
        fallbacks=[])

    class _Svc:
        def get_case(self, cid):
            return case

    class _H:
        default_tenant = "VN"
        service = _Svc()

        def reply_ex(self, key, **kw):
            return ChatReply("Đang tạo file Word có nhận xét…", "export_doc", "case-1")

    s = _FakeSender()
    _process(_H(), s, "k", "C1", "xuất file", None, None, "th", 10 * 1024 * 1024, True)
    assert getattr(s, "uploaded", []) and s.uploaded[0][1] == "ra-soat-co-nhan-xet.docx"
    assert any("đang tạo file" in t.lower() for _, t in s.sent)   # ack đã gửi


def test_make_progress_cb_throttles_and_only_on_increase():
    # Heartbeat A1: callback update ack CHỈ khi #rủi ro TĂNG và cách ≥8s (chống spam chat.update).
    from legalguard.adapters.inbound.channels import _make_progress_cb
    s = _FakeSender()
    cb = _make_progress_cb(s, "C1", "111.222")
    cb({"risks": 2})              # lần đầu, n>0 → update
    cb({"risks": 2})              # n không tăng → bỏ
    cb({"risks": 3})             # tăng NHƯNG <8s từ lần trước → throttle bỏ
    updated = getattr(s, "updated", [])
    assert len(updated) == 1
    assert "2 rủi ro" in updated[0][2]
    assert updated[0][1] == "111.222"           # đúng ts ack


def test_make_progress_cb_ignores_zero():
    from legalguard.adapters.inbound.channels import _make_progress_cb
    s = _FakeSender()
    cb = _make_progress_cb(s, "C1", "111.222")
    cb({"risks": 0})
    assert not getattr(s, "updated", [])         # chưa có rủi ro → không update


def test_is_reformat_request_detects_intent():
    from legalguard.adapters.inbound.channels import _is_reformat_request
    assert _is_reformat_request("cho tôi bản email")
    assert _is_reformat_request("format lại giúp tôi") and _is_reformat_request("trình bày lại")
    assert _is_reformat_request("rút gọn lại") and _is_reformat_request("viết trang trọng hơn")
    assert _is_reformat_request("dạng memo") and _is_reformat_request("as an email")
    assert not _is_reformat_request("mức phạt tối đa bao nhiêu?")        # câu hỏi
    assert not _is_reformat_request("đối tác đồng ý giảm phạt còn 10%")  # counter-offer


def test_reformat_email_deterministic_keeps_substance():
    from legalguard.domain.models import Conversation
    h = _handler()
    conv = Conversation(id="c", context="deal")
    conv.add("assistant", "Sau khi rà soát… (1) Tại điều khoản “Điều 5”: phạt 15% vượt trần.")
    out = h._reformat(conv, "cho tôi bản email", "vi")
    assert out.startswith("Kính gửi Quý Công ty,")
    assert "(1) Tại điều khoản “Điều 5”: phạt 15% vượt trần." in out   # GIỮ NGUYÊN nội dung
    assert "Trân trọng." in out and out.count("trí tuệ nhân tạo") == 1  # công bố 1 lần


def test_reformat_no_previous_review():
    from legalguard.domain.models import Conversation
    out = _handler()._reformat(Conversation(id="c", context="deal"), "bản email", "vi")
    assert "Chưa có nội dung" in out


def test_reformat_non_email_offline_returns_prev():
    # judge/reasoner stub (offline) → giọng khác trả NGUYÊN BẢN (không mất nội dung, không bịa).
    from legalguard.domain.models import Conversation
    h = _handler()
    conv = Conversation(id="c", context="deal")
    conv.add("assistant", "Nội dung tư vấn gốc giữ nguyên.")
    out = h._reformat(conv, "rút gọn giúp", "vi")
    assert "Nội dung tư vấn gốc giữ nguyên." in out


def test_reformat_routing_in_deal():
    # Trong deal, "cho tôi bản email" → nhánh trình-bày-lại (không nhầm counter-offer/followup).
    h = _handler()
    h.reply("cRe", text="Bên B chịu phạt 15% giá trị hợp đồng; tranh chấp bằng trọng tài Bắc Kinh.")
    out = h.reply("cRe", text="cho tôi bản email")
    assert out.startswith("Kính gửi Quý Công ty,") and "Trân trọng." in out


def test_trust_query_returns_accuracy_publication():
    # Hỏi về độ tin cậy (meta) → trả công bố độ chính xác, KHÔNG đi lookup/analyze.
    out = _handler().reply("cT", text="Độ chính xác của hệ thống thế nào, có đáng tin không?")
    assert "Độ tin cậy" in out and "Groundedness" in out


def test_counter_offer_in_deal_routes_negotiation():
    # Trong deal, tin là PHẢN HỒI đối tác (không phải câu hỏi) → vòng ĐÀM PHÁN có cấu trúc.
    from legalguard.adapters.inbound.channels import _is_counter_offer
    assert _is_counter_offer("Đối tác đồng ý giảm phạt còn 10% nhưng giữ trọng tài Bắc Kinh.")
    assert not _is_counter_offer("Mức phạt tối đa là bao nhiêu?")     # câu hỏi → KHÔNG phải counter
    h = _handler()
    h.reply("cNego", text=MSG)                                        # analyze → set context
    r = h.reply_ex("cNego", text="Đối tác đồng ý giảm phạt còn 10%, nhưng từ chối đổi trọng tài.")
    assert r.kind == "negotiate"                                      # → vòng đàm phán


def test_partner_refusal_with_contract_keyword_routes_negotiation_not_analyze():
    # Đo từ test LIVE: tin từ chối "chúng tôi không thể đổi… bắt buộc" chứa từ khóa HĐ ("trọng tài")
    # từng bị RE-ANALYZE oan (guardrail walk-away không chạy). Giờ phải ra vòng đàm phán.
    from legalguard.adapters.inbound.channels import _is_counter_offer
    assert _is_counter_offer("Về trọng tài, chúng tôi không thể đổi, bắt buộc phải ở Bắc Kinh.")
    h = _handler()
    h.reply("cNego2", text=MSG)                                       # analyze → set context (deal)
    r = h.reply_ex("cNego2", text="Về trọng tài, chúng tôi không thể đổi, bắt buộc phải ở Bắc Kinh.")
    assert r.kind == "negotiate"                                      # KHÔNG phải "analysis"


def test_short_in_deal_message_not_reanalyzed():
    # Trong deal, tin NGẮN chứa từ khóa HĐ nhưng không phải HĐ mới → không re-analyze (rơi xuống đàm phán/followup).
    h = _handler()
    h.reply("cShort", text=MSG)                                       # deal context
    r = h.reply_ex("cShort", text="Giữ nguyên điều khoản thanh toán nhé.")
    assert r.kind != "analysis"


def test_format_negotiation_reply():
    from legalguard.adapters.inbound.channels import format_negotiation_reply
    out = format_negotiation_reply({"status": "close", "assessment": "đối tác nhượng đủ",
                                    "strategy": "chốt", "reply_vi": "Đồng ý", "grounded": True})
    assert "Nên chốt thỏa thuận" in out and "đối tác nhượng đủ" in out and "Đồng ý" in out
    assert "🔄" not in out and "📊" not in out and "✅" not in out   # văn phong pháp lý, không icon


def test_ai_disclosure_on_chat_replies():
    # Minh bạch AI (Luật AI 134/2025): mọi reply chat phải cho biết là AI trả lời.
    from legalguard.adapters.inbound.channels import format_chat_reply, format_negotiation_reply
    from legalguard.domain.models import AnalysisResult
    res = AnalysisResult(tenant="VN", risks=[{"clause": "X", "risk": "y", "priority": "negotiate"}],
                         fallbacks=[], needs_human_review=False, review_reasons=[], summary="", trace=[],
                         strategy="s")
    assert "AI" in format_chat_reply(res)
    nego = format_negotiation_reply({"status": "continue", "assessment": "a", "reply_vi": "x", "grounded": True})
    assert "AI" in nego


def test_format_negotiation_reply_shows_ledger_and_walk_away():
    from legalguard.adapters.inbound.channels import format_negotiation_reply
    out = format_negotiation_reply({"status": "walk_away", "assessment": "đối tác giữ Bắc Kinh",
                                    "reply_vi": "x", "grounded": True, "walk_away_recommended": True,
                                    "state": {"secured": ["phạt 8%"], "conceded": ["gia hạn 5 ngày"]}})
    assert "Đã chốt:" in out and "phạt 8%" in out and "Ta đã nhượng:" in out and "cân nhắc rút" in out


def test_format_negotiation_reply_shows_next_moves():
    from legalguard.adapters.inbound.channels import format_negotiation_reply
    out = format_negotiation_reply({"status": "continue", "assessment": "a", "reply_vi": "x", "grounded": True,
                                    "next_moves": [{"offer": "gia hạn giao 5 ngày", "in_return_for": "chốt phạt 8%",
                                                    "near_red_line": False},
                                                   {"offer": "đổi trọng tài", "near_red_line": True}]})
    assert "thang nhượng-bộ" in out and "gia hạn giao 5 ngày" in out
    assert "đổi lấy: chốt phạt 8%" in out and "gần điểm sống còn" in out


def test_analyze_seeds_red_lines_into_nego_state():
    from legalguard.domain.negotiation import state_from_json
    h = _handler()
    h.reply("cRed", text=MSG)                                  # analyze → seed red_lines = must_fix
    st = state_from_json(h.store.get("cRed").nego_state)
    assert st.red_lines                                        # trọng tài Bắc Kinh = must_fix → là red-line
    assert any("trọng tài" in r.lower() or "bắc kinh" in r.lower() for r in st.red_lines)


def test_chat_history_redacts_pii_before_store():
    # Khách DÁN hợp đồng có PII vào chat → history KHÔNG được giữ email/sđt nguyên văn.
    store = InMemoryConversationStore()
    h = ChatHandler(build_service(), build_parser(), store, "VN")
    h.reply("cPII", text="Điều khoản trọng tài; liên hệ a@example.com, sđt 0912345678")
    hist = store.get("cPII").history
    joined = " ".join(m["content"] for m in hist if m["role"] == "user")
    assert "a@example.com" not in joined and "0912345678" not in joined   # đã redact
    assert "trọng tài" in joined.lower()                                  # vẫn giữ ngữ cảnh pháp lý


def test_conversation_remembers_context_and_history():
    store = InMemoryConversationStore()
    h = ChatHandler(build_service(), build_parser(), store, "VN")
    h.reply("c9", text=MSG)                              # lượt 1: rà soát → set context
    conv = store.get("c9")
    assert "trọng tài" in conv.context.lower()           # nhớ deal đang bàn
    assert len(conv.history) == 2

    out = h.reply("c9", text="Nếu đối tác từ chối SIAC thì sao?")   # follow-up (không có tín hiệu HĐ)
    assert out                                           # trả lời tiếp (stub) — không rà soát lại
    assert len(store.get("c9").history) == 4             # tích lũy lịch sử


# ---- Slack ----
def test_slack_challenge_and_signature():
    c = _client(slack="slacksecret")
    r = _slack_post(c, "slacksecret", {"type": "url_verification", "challenge": "abc123"})
    assert r.json() == {"challenge": "abc123"}


def test_slack_rejects_bad_signature():
    c = _client(slack="slacksecret")
    r = c.post("/channels/slack/events", content=b"{}",
               headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=bad"})
    assert r.status_code == 401


def test_slack_message_returns_reply():
    c = _client(slack="slacksecret")
    r = _slack_post(c, "slacksecret", {"event": {"text": MSG}})
    assert "Điều khoản trọng tài" in r.json()["reply"]


# ---- Zalo ----
def test_zalo_message_and_signature():
    secret, appid = "zalosecret", "app1"
    c = _client(zalo=secret, appid=appid)
    ts = str(int(time.time()))      # timestamp tươi (qua replay check)
    body = json.dumps({"timestamp": ts, "message": {"text": MSG}}).encode()
    mac = "mac=" + hashlib.sha256((appid + body.decode() + ts + secret).encode()).hexdigest()
    r = c.post("/channels/zalo/webhook", content=body, headers={"X-ZEvent-Signature": mac})
    assert "Điều khoản trọng tài" in r.json()["reply"]


def test_zalo_rejects_bad_signature():
    c = _client(zalo="zalosecret", appid="app1")
    body = json.dumps({"timestamp": "111", "message": {"text": "x"}}).encode()
    r = c.post("/channels/zalo/webhook", content=body, headers={"X-ZEvent-Signature": "mac=bad"})
    assert r.status_code == 401


# ---- Outbound: gửi reply + tải file ----
def test_slack_sends_reply_via_sender():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    r = _slack_post(c, "s", {"event": {"text": MSG, "channel": "C123"}})
    assert r.json() == {"ok": True}                       # ack nhanh
    assert sender.sent and sender.sent[0][0] == "C123"    # đã gửi về đúng channel
    assert "Đã nhận" in sender.sent[0][1]                 # ack tức thì trước khi phân tích
    assert "Điều khoản trọng tài" in sender.sent[-1][1]   # rồi mới tới kết quả


def test_per_conversation_lock_no_lost_updates():
    # 2 tin ĐỒNG THỜI cùng 1 hội thoại → lock tuần tự hóa → KHÔNG mất lượt (chống last-write-wins).
    import threading
    h = _handler()

    def ask(msg):
        h.reply("cRACE", text=msg)

    threads = [threading.Thread(target=ask, args=(f"Mức phạt vi phạm hợp đồng là bao nhiêu {i}?",))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    hist = h.store.get("cRACE").history
    assert len(hist) == 8                  # 4 user + 4 assistant — không lượt nào bị đè mất


def test_mrkdwn_blocks_splits_long_reply_no_truncation():
    # Reply dài (HĐ nhiều rủi ro) phải chia nhiều block, KHÔNG cụt, mỗi block ≤ 3000 ký tự.
    long_reply = "\n".join(f"🔴 Điều {i}: rủi ro chi tiết tiếng Việt có dấu" for i in range(300))
    blocks = _mrkdwn_blocks(long_reply)
    assert len(blocks) >= 2                                          # chia nhiều block
    assert all(len(b["text"]["text"]) <= 3000 for b in blocks)      # không vượt giới hạn Slack
    joined = "\n".join(b["text"]["text"] for b in blocks)
    assert "Điều 0:" in joined and "Điều 299:" in joined            # giữ cả đầu lẫn cuối (không cụt)


def test_mrkdwn_blocks_short_reply_single_block():
    blocks = _mrkdwn_blocks("Rủi ro: trọng tài Bắc Kinh.")
    assert len(blocks) == 1 and blocks[0]["type"] == "section"


def test_slack_reply_threads_under_top_level_message():
    # Mention ở CẤP CHANNEL (không thread_ts) → ack + reply phải thread NGAY DƯỚI tin người hỏi (dùng ts).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "ts": "111.22"}})
    assert sender.threads and all(t == "111.22" for t in sender.threads)


def test_slack_reply_stays_in_existing_thread():
    # Hỏi TRONG thread → reply đúng thread gốc (thread_ts), không tách theo ts tin mới.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "ts": "999.00", "thread_ts": "111.22"}})
    assert sender.threads and all(t == "111.22" for t in sender.threads)


def test_slack_acks_lookup_question_not_silent():
    # Câu hỏi pháp lý (lookup, ~30s) → phải gửi ack "đang tra cứu" trước, không để user chờ im.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?",
                                   "channel": "C1", "ts": "1.1"}})
    assert sender.sent and "tra cứu" in sender.sent[0][1].lower()   # ack tra cứu đi trước
    assert len(sender.sent) >= 2                                     # ack + kết quả


def test_slack_no_ack_for_casual_message():
    # Tin xã giao (không phải câu hỏi) → KHÔNG ack tra cứu (tránh phiền).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "cảm ơn nhé", "channel": "C1", "ts": "2.2"}})
    assert all("tra cứu" not in t.lower() for _, t in sender.sent)


def test_slack_ignores_bot_messages_no_reply_loop():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    r = _slack_post(c, "s", {"event": {"text": "reply của bot", "channel": "C123",
                                       "bot_id": "B042"}})
    assert r.json() == {"ok": True}
    assert sender.sent == []                              # không tự trả lời chính mình


def test_slack_ignores_retry_deliveries():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    body = json.dumps({"event": {"text": MSG, "channel": "C1"}}).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"s", b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    r = c.post("/channels/slack/events", content=body,
               headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                        "X-Slack-Retry-Num": "1"})       # bản giao lại (at-least-once)
    assert r.json() == {"ok": True}
    assert sender.sent == []                              # không xử lý trùng


def test_slack_ignores_message_edits_and_deletes():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    for subtype in ("message_changed", "message_deleted"):
        _slack_post(c, "s", {"event": {"subtype": subtype, "channel": "C1"}})
    assert sender.sent == []                              # edit/xóa tin không kích hoạt bot


def test_slack_replies_in_thread_when_asked_in_thread():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": MSG, "channel": "C1", "thread_ts": "171.001"}})
    assert len(sender.threads) == 2                        # ack + kết quả
    assert all(t == "171.001" for t in sender.threads)     # cả hai đúng thread


def test_slack_ack_sent_before_file_analysis():
    sender = _FakeSender(file_bytes=MSG.encode())
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "", "channel": "C1",
                                   "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}})
    assert "Đã nhận" in sender.sent[0][1]                  # ack trước
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # kết quả sau


def test_slack_no_ack_for_quick_followup():
    # Câu hỏi thường (không tín hiệu HĐ, không file) → trả lời thẳng, KHÔNG ack (tránh ồn).
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"event": {"text": "xin chào bạn nhé", "channel": "C1"}})
    assert len(sender.sent) == 1
    assert "Đã nhận" not in sender.sent[0][1]


def test_slack_app_mention_strips_tag_and_analyzes():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"authorizations": [{"user_id": "U99"}],
                         "event": {"type": "app_mention", "channel": "C1",
                                   "text": f"<@U99> {MSG}"}})
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # mention → vẫn rà soát
    # tag @bot không lọt vào nội dung phân tích (không nằm trong reply prompt nào)


def test_slack_message_with_bot_mention_deduped():
    # Channel bot là member: cùng 1 tin mention sinh CẢ event message lẫn app_mention
    # (cùng ts). Event đến TRƯỚC xử lý, event sau bị dedup → khách nhận đúng 1 reply.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    base = {"authorizations": [{"user_id": "U99"}]}
    _slack_post(c, "s", {**base, "event": {"type": "message", "channel": "C1",
                                           "ts": "111.222", "text": f"<@U99> {MSG}"}})
    assert len(sender.sent) == 2                           # message tới trước: ack + kết quả
    _slack_post(c, "s", {**base, "event": {"type": "app_mention", "channel": "C1",
                                           "ts": "111.222", "text": f"<@U99> {MSG}"}})
    assert len(sender.sent) == 2                           # app_mention cùng ts → bỏ qua
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # tag @bot đã bóc, vẫn rà soát


def test_slack_mention_with_file_uses_message_event_files():
    # Mention + đính kèm file: event `message` (chắc chắn có files) tới trước → file
    # được tải và phân tích; app_mention (có thể thiếu files) tới sau bị dedup.
    sender = _FakeSender(file_bytes=MSG.encode())
    c = _client(slack="s", slack_sender=sender)
    base = {"authorizations": [{"user_id": "U99"}]}
    _slack_post(c, "s", {**base, "event": {
        "type": "message", "subtype": "file_share", "channel": "C1", "ts": "222.333",
        "text": "<@U99> xem giúp", "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}})
    _slack_post(c, "s", {**base, "event": {"type": "app_mention", "channel": "C1",
                                           "ts": "222.333", "text": "<@U99> xem giúp"}})
    assert sender.downloaded == ["https://files/x"]        # file được tải đúng 1 lần
    assert len(sender.sent) == 2                           # ack + kết quả
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # phân tích nội dung file


def test_slack_mention_other_user_still_processed():
    # Mention NGƯỜI KHÁC (không phải bot) thì vẫn là tin nhắn thường → xử lý bình thường.
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", {"authorizations": [{"user_id": "U99"}],
                         "event": {"type": "message", "channel": "C1",
                                   "text": f"<@U42> xem giúp: {MSG}"}})
    assert len(sender.sent) == 2                           # ack + kết quả


def test_slack_rejects_oversize_attachment():
    sender = _FakeSender(file_bytes=b"x" * 2048)          # file "tải về" 2KB
    handler = _handler()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="s",
                                             slack_sender=sender, max_upload_bytes=1024,
                                             mention_only=False))
    c = TestClient(app)
    _slack_post(c, "s", {"event": {"text": "", "channel": "C1",
                                   "files": [{"url_private": "https://files/big", "name": "x.pdf"}]}})
    assert "quá lớn" in sender.sent[-1][1]                # báo khách, không phân tích


def test_slack_downloads_attachment_then_analyzes():
    sender = _FakeSender(file_bytes=MSG.encode())          # "file" tải về = nội dung HĐ
    c = _client(slack="s", slack_sender=sender)
    payload = {"event": {"text": "", "channel": "C1",
                         "files": [{"url_private": "https://files/x", "name": "hd.txt"}]}}
    _slack_post(c, "s", payload)
    assert sender.downloaded == ["https://files/x"]        # đã tải file
    assert "Điều khoản trọng tài" in sender.sent[-1][1]    # phân tích nội dung file


# ---- Slack feedback (interactive buttons) ----
def _slack_interaction(client, secret, action_id, value, extra=None):
    import urllib.parse
    payload = {"type": "block_actions", "user": {"id": "U1"}, "channel": {"id": "C1"},
               "actions": [{"action_id": action_id, "value": value}]}
    if extra:
        payload.update(extra)
    body = ("payload=" + urllib.parse.quote(json.dumps(payload))).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post("/channels/slack/interactions", content=body,
                       headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                                "Content-Type": "application/x-www-form-urlencoded"})


def test_slack_interaction_records_feedback():
    c = _client(slack="sek")
    r = _slack_interaction(c, "sek", "fb_wrong", json.dumps({"k": "lookup", "r": "phạt vi phạm?"}))
    assert r.status_code == 200
    assert r.json().get("replace_original") is True        # thay tin gốc bằng xác nhận


def test_record_deal_outcome_per_clause():
    # Ghi Outcome cho MỌI fallback của case → nuôi win-rate; cô lập org.
    from legalguard.adapters.inbound.channels import _record_deal_outcome
    from legalguard.domain.models import AnalysisCase

    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False, risks=[],
                        fallbacks=[{"clause": "Điều A"}, {"clause": "Điều B"}, {"clause": ""}], trace=[])

    class _Svc:
        def __init__(self): self.recorded = []
        def get_case(self, cid): return case if cid == "c1" else None
        def record_outcome(self, o): self.recorded.append(o)

    svc = _Svc()
    assert _record_deal_outcome(svc, "default", "c1", "accepted") == 2   # bỏ clause rỗng
    assert {o.clause for o in svc.recorded} == {"Điều A", "Điều B"}
    assert all(o.result == "accepted" for o in svc.recorded)
    assert _record_deal_outcome(svc, "other-org", "c1", "accepted") == 0  # sai org → không ghi
    assert _record_deal_outcome(svc, "default", "nope", "accepted") == 0   # không có case


def test_record_deal_outcome_covers_risk_clauses_when_no_fallback():
    # Agent thỉnh thoảng bỏ propose_fallback → vẫn ghi outcome theo clause của RISK (không 0).
    from legalguard.adapters.inbound.channels import _record_deal_outcome
    from legalguard.domain.models import AnalysisCase

    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[{"clause": "Điều 5"}, {"clause": "Điều 8"}], fallbacks=[], trace=[])

    class _Svc:
        def __init__(self): self.recorded = []
        def get_case(self, cid): return case
        def record_outcome(self, o): self.recorded.append(o)

    svc = _Svc()
    assert _record_deal_outcome(svc, "default", "c1", "partial") == 2   # theo risk clause khi thiếu fallback
    assert {o.clause for o in svc.recorded} == {"Điều 5", "Điều 8"}


def test_slack_interaction_records_outcome():
    # (tương thích ngược) tin phân tích CŨ vẫn còn nút oc_* → handler xử lý được.
    c = _client(slack="sek")
    r = _slack_interaction(c, "sek", "oc_accepted", json.dumps({"c": "case-xyz"}))
    assert r.status_code == 200 and r.json().get("replace_original") is True
    assert "kết quả" in r.json()["text"].lower()        # xác nhận ghi kết quả (flywheel)


def test_review_action_blocks_two_buttons():
    # Reply rà soát: Chốt / Sửa lại + nút 📄 Bản đối chiếu (khi có case_id).
    from legalguard.adapters.inbound.channels import _review_action_blocks
    blocks = _review_action_blocks("analysis", "case1")
    assert len(blocks) == 1 and blocks[0]["block_id"] == "lg_review"
    els = blocks[0]["elements"]
    assert [e["action_id"] for e in els] == ["rv_close", "rv_revise", "redline_dl"]
    assert els[0]["text"]["text"] == "Chốt" and els[1]["text"]["text"] == "Sửa lại"
    # không có case_id → không có nút tải file
    assert len(_review_action_blocks("analysis", "")[0]["elements"]) == 2


def test_redline_items_from_case_maps_old_new():
    from legalguard.adapters.inbound.channels import _redline_items_from_case
    from legalguard.domain.models import AnalysisCase
    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=True, trace=[],
                        risks=[{"clause": "Phạt 15%", "evidence": "Phạt 15%.", "legal_status": "illegal",
                                "violated_law": "Điều 301",
                                "counter_clause": {"vi": "Tối đa 8%.", "en": "Cap 8%.", "rationale": "Đ.301"}},
                               {"clause": "TT 90 ngày", "evidence": "TT 90 ngày."}],
                        fallbacks=[{"clause": "TT 90 ngày", "suggestion": "rút 30 ngày"}])
    items = _redline_items_from_case(case)
    assert items[0]["evidence"] == "Phạt 15%." and items[0]["vi"] == "Tối đa 8%." and items[0]["en"] == "Cap 8%."
    assert items[1]["vi"] == "rút 30 ngày"          # không có counter → dùng suggestion fallback


def test_send_redline_uploads_docx():
    from dataclasses import asdict

    import pytest
    pytest.importorskip("docx")
    from legalguard.adapters.inbound.channels import _send_redline
    from legalguard.domain.models import AnalysisCase
    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=True, trace=[],
                        risks=[{"clause": "Phạt 15%", "evidence": "Phạt 15%.", "legal_status": "illegal",
                                "counter_clause": {"vi": "Tối đa 8%.", "en": "Cap 8%."}}], fallbacks=[])

    class _Svc:
        def get_case(self, cid):
            return case if cid == "c1" else None

        def compile_redline(self, items, title="", protected_party=""):
            from legalguard.domain.amendments import compile_redline
            return asdict(compile_redline(items, title=title, protected_party=protected_party))

    sender = _FakeSender()
    _send_redline(_Svc(), sender, "default", "c1", "C1", "th1")
    up = getattr(sender, "uploaded", [])
    assert len(up) == 1 and up[0][1] == "ban-doi-chieu-sua-doi.docx" and up[0][3] == "th1"
    assert up[0][2] > 500                            # docx bytes
    assert any("đang tạo bản đối chiếu" in t.lower() for _, t in sender.sent)   # phản hồi tức thì khi bấm


def test_send_redline_wrong_org_or_missing():
    from legalguard.adapters.inbound.channels import _send_redline

    class _Svc:
        def get_case(self, cid):
            return None

    sender = _FakeSender()
    _send_redline(_Svc(), sender, "default", "nope", "C1", "th1")
    assert not getattr(sender, "uploaded", [])       # không upload
    assert "không tìm thấy" in sender.sent[-1][1].lower()


def test_slack_interaction_rv_close_records_accepted_and_helpful():
    c = _client(slack="sek")
    r = _slack_interaction(c, "sek", "rv_close",
                           json.dumps({"k": "analysis", "r": "case-xyz", "c": "case-xyz"}))
    assert r.status_code == 200 and r.json().get("replace_original") is True
    assert "chốt" in r.json()["text"].lower()


def test_slack_interaction_rv_revise_asks_and_keeps_analysis():
    # 'Sửa lại' MỚI = hỏi 'muốn sửa gì' + GIỮ bài (KHÔNG replace_original) + đặt pending_edit cho thread.
    sender = _FakeSender()
    c = _client(slack="sek", slack_sender=sender)
    r = _slack_interaction(c, "sek", "rv_revise", json.dumps({"k": "analysis", "r": "cX", "c": "cX"}),
                           extra={"container": {"thread_ts": "T1"}, "message": {"ts": "m1"}})
    assert r.json() == {"ok": True}                                  # KHÔNG replace_original → giữ bài phân tích
    assert any("muốn sửa" in t.lower() for _, t in sender.sent)      # bot hỏi muốn sửa gì
    assert sender.threads[-1] == "T1"                                # hỏi trong đúng thread


def test_rv_revise_interaction_writes_pending_edit_to_store():
    # Mắt xích end-to-end: bấm 'Sửa lại' (interaction) → ghi pending_edit vào CÙNG store mà tin kế của user đọc.
    handler = ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="sek", slack_sender=_FakeSender()))
    client = TestClient(app)
    _slack_interaction(client, "sek", "rv_revise", json.dumps({"k": "analysis", "r": "cX", "c": "cX"}),
                       extra={"container": {"thread_ts": "T1"}, "message": {"ts": "m1"}})
    conv = handler.store.get("slack:C1:T1")               # channel C1 (payload) + thread T1 → conv_key
    assert conv is not None and conv.pending_edit == "cX"   # tin kế trong thread sẽ route revise


def test_revise_reply_passes_mention_gate_when_pending_edit():
    # BUG e2e (mention-only ON): user trả lời yêu cầu 'Sửa lại' KHÔNG @bot → TRƯỚC đây bị gate im lặng →
    # luồng revise treo. Fix: thread đang chờ pending_edit → cho qua gate + route revise.
    from legalguard.domain.models import AnalysisCase, Conversation
    from legalguard.domain.tenants import default_org
    handler = ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")
    org = default_org("VN")
    handler.service.cases.save(AnalysisCase(
        id="cR", org_id=org.id, tenant="VN", created_at="t", lang="vi", contract_excerpt="",
        summary="", needs_human_review=False,
        risks=[{"clause": "Điều 5", "risk": "phạt 15%"}], fallbacks=[], trace=[]))

    class _R:
        available = True

        def complete(self, prompt, *, system=None):
            return "SỬA Điều 5: 15 ngày"

    handler.service.reasoner = _R()
    handler.store.save(Conversation(id="slack:C1:T1", context="deal", pending_edit="cR"))
    sender = _FakeSender()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="s",
                                             slack_sender=sender, mention_only=True))
    client = TestClient(app)
    r = _slack_post(client, "s", {"authorizations": [{"user_id": "UBOT"}], "event": {
        "type": "message", "channel": "C1", "user": "U1",
        "text": "Điều 5 đổi thời hạn 15 ngày", "ts": "111.9", "thread_ts": "T1"}})   # KHÔNG @bot
    assert r.status_code == 200
    joined = " ".join(t for _, t in sender.sent)
    assert "SỬA Điều 5" in joined                                   # qua gate + route revise (không im lặng)
    assert handler.store.get("slack:C1:T1").pending_edit == ""      # đã xử lý → xóa cờ


def test_non_mention_chatter_still_silent_without_pending_edit():
    # Không có pending_edit → tin thread không @bot VẪN im lặng (giữ mention-gate cho chatter thường).
    handler = ChatHandler(build_service(), build_parser(), InMemoryConversationStore(), "VN")
    sender = _FakeSender()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="s",
                                             slack_sender=sender, mention_only=True))
    client = TestClient(app)
    r = _slack_post(client, "s", {"authorizations": [{"user_id": "UBOT"}], "event": {
        "type": "message", "channel": "C1", "user": "U1", "text": "anh em ăn trưa chưa",
        "ts": "222.1", "thread_ts": "T9"}})
    assert r.status_code == 200 and r.json() == {"ok": True} and not sender.sent   # im lặng


def test_pending_edit_routes_to_revise_and_clears():
    # Đang chờ 'Sửa lại' (pending_edit) → tin kế = yêu cầu sửa → soạn lại (KHÔNG rà soát lại) + xóa cờ.
    from legalguard.domain.models import AnalysisCase, Conversation
    from legalguard.domain.tenants import default_org
    h = _handler()
    org = default_org("VN")
    h.service.cases.save(AnalysisCase(
        id="cE", org_id=org.id, tenant="VN", created_at="t", lang="vi", contract_excerpt="",
        summary="", needs_human_review=False,
        risks=[{"clause": "Điều 5", "risk": "phạt 15%"}], fallbacks=[], trace=[]))

    class _R:
        available = True

        def complete(self, prompt, *, system=None):
            return "SỬA Điều 5: thời hạn 15 ngày"     # bản sửa (chứng: đã route revise, không rà lại)

    h.service.reasoner = _R()
    h.store.save(Conversation(id="kEdit", context="deal đang bàn", pending_edit="cE"))
    r = h.reply_ex("kEdit", text="Điều 5 đổi thời hạn còn 15 ngày")
    assert "SỬA Điều 5" in r.text                       # đã soạn lại theo ý (không phải reply rà soát/lookup)
    assert h.store.get("kEdit").pending_edit == ""      # one-shot: cờ đã xóa


def test_revise_clause_offline_safe():
    # revise_clause bám yêu cầu; lỗi LLM → khung an toàn, KHÔNG bịa.
    from legalguard.domain.models import AnalysisCase
    h = _handler()
    case = AnalysisCase(id="c", org_id="o", tenant="VN", created_at="t", lang="vi", contract_excerpt="",
                        summary="", needs_human_review=False,
                        risks=[{"clause": "Điều 5", "risk": "phạt 15%"}], fallbacks=[], trace=[])

    class _Err:
        available = True

        def complete(self, prompt, *, system=None):
            from legalguard.domain.ports import LLMError
            raise LLMError("qwen", "down")

    h.service.reasoner = _Err()
    out = h.service.revise_clause(case, "Điều 5 đổi 15 ngày", "vi")
    assert "chưa soạn được" in out.lower()             # khung an toàn


def test_slack_interaction_rv_close_updates_via_response_url(monkeypatch):
    # CÓ response_url → cập nhật tin QUA response_url (HTTP response trực tiếp bị Slack bỏ qua trên WS này).
    import httpx
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured["url"], captured["body"] = url, json
        class _R:
            status_code = 200
        return _R()
    monkeypatch.setattr(httpx, "post", _fake_post)
    c = _client(slack="sek")
    r = _slack_interaction(c, "sek", "rv_close", json.dumps({"k": "analysis", "r": "cx", "c": "cx"}),
                           extra={"response_url": "https://hooks.slack.test/rv", "message": {"ts": "m1"}})
    assert r.json() == {"ok": True}                                    # HTTP chỉ ack
    assert captured["url"] == "https://hooks.slack.test/rv"            # cập nhật đi qua response_url
    assert captured["body"]["replace_original"] is True and "chốt" in captured["body"]["text"].lower()


def test_slack_interaction_bad_signature_401():
    c = _client(slack="sek")
    r = c.post("/channels/slack/interactions", content=b"payload=%7B%7D",
               headers={"X-Slack-Request-Timestamp": "0", "X-Slack-Signature": "v0=bad"})
    assert r.status_code == 401


# ---- Phase 2: rút gợi ý 'bên mình bảo vệ' từ chỉ dẫn chat ----
def test_extract_protected_hint():
    from legalguard.adapters.inbound.channels import _extract_protected_hint
    assert _extract_protected_hint("help me review this contract for Phu Quoc side") == "Phu Quoc"
    assert _extract_protected_hint("rà soát giúp, bảo vệ Công ty ABC.") == "Công ty ABC"
    assert _extract_protected_hint("review for me") == ""            # stopword → không nhận
    assert _extract_protected_hint("phân tích hợp đồng này giúp") == ""   # không có trigger


# ---- Phase 4: nút "Đồng ý sửa" per-risk → soạn điều khoản sửa (cũ→mới) ----
def _amend_result():
    return AnalysisResult(tenant="VN",
        risks=[{"clause": "Phạt 15%", "risk": "vượt trần"}, {"clause": "Tòa SG", "risk": "bất lợi"}],
        fallbacks=[{"clause": "Phạt 15%", "suggestion": "giảm về 8%"}],   # chỉ rủi ro 1 có đề xuất
        needs_human_review=True, review_reasons=[], summary="", trace=[], strategy="Đưa về VIAC")


def test_analysis_blocks_agree_button_per_risk():
    from legalguard.adapters.inbound.channels import _analysis_blocks
    blocks = _analysis_blocks(_amend_result(), "case1")
    buttons = [el for b in blocks if b["type"] == "actions" for el in b["elements"]]   # nút ở actions block dưới
    assert len(buttons) == 2                                # nút cho MỌI rủi ro (kể cả không có fallback)
    assert all(b["action_id"] == "amend_ok" and b["text"]["text"] == "Đồng ý sửa" for b in buttons)
    assert json.loads(buttons[0]["value"]) == {"c": "case1", "i": 0}
    assert json.loads(buttons[1]["value"]) == {"c": "case1", "i": 1}   # rủi ro không có đề xuất VẪN có nút
    dump = json.dumps(blocks, ensure_ascii=False)
    assert "(1) Tại điều khoản" in dump and "(2) Tại điều khoản" in dump
    assert "🔴" not in dump and "⚖️" not in dump and "📋" not in dump   # văn phong pháp lý, không icon


def test_analysis_blocks_caps_at_slack_limit():
    # Slack chặn 50 block/tin → HĐ rất nhiều rủi ro phải bị CẮT (≤48) + ghi chú, không vỡ chat.postMessage.
    from legalguard.adapters.inbound.channels import _analysis_blocks
    res = AnalysisResult(tenant="VN",
        risks=[{"clause": f"Điều {i}", "risk": "bất lợi"} for i in range(60)],
        fallbacks=[], needs_human_review=True, review_reasons=[], summary="", trace=[], strategy="giữ")
    blocks = _analysis_blocks(res, "c1")
    assert len(blocks) <= 48                                # dưới trần Slack (chừa chỗ nút Chốt/Sửa lại)
    assert "rút gọn" in json.dumps(blocks, ensure_ascii=False)
    assert blocks[-1]["type"] == "context"                 # dòng công bố AI vẫn ở cuối


def test_analysis_blocks_no_button_without_case_id():
    from legalguard.adapters.inbound.channels import _analysis_blocks
    blocks = _analysis_blocks(_amend_result(), "")         # không case_id → không thể nạp lại → không nút
    assert not any(b["type"] == "actions" for b in blocks)   # không có actions block (nút) nào


# ---- Khối 4 phần (cũ → mới → lý do): counter_clause inline cho illegal/must_fix, nút cho rủi ro nhẹ ----
def _counter_result():
    return AnalysisResult(tenant="VN",
        risks=[
            {"clause": "Phạt 15%", "risk": "vượt trần", "legal_status": "illegal",
             "violated_law": "Điều 301", "evidence": "Bên B chịu phạt 15% giá trị hợp đồng.",
             "counter_clause": {"vi": "Mức phạt tối đa 8% phần vi phạm.", "en": "Cap 8%.",
                                "rationale": "Điều 301 LTM 2005 giới hạn 8%.", "grounded": True}},
            {"clause": "Thanh toán 90 ngày", "risk": "bất lợi dòng tiền"},
        ],
        fallbacks=[{"clause": "Thanh toán 90 ngày", "suggestion": "rút về 30-45 ngày"}],
        needs_human_review=True, review_reasons=[], summary="", trace=[], strategy="")


def test_risk_segments_four_part_block_with_inline_counter():
    from legalguard.adapters.inbound.channels import _risk_segments
    _num, _idx, _clause, seg, show_button = _risk_segments(_counter_result())[0]
    # nhãn IN ĐẬM markdown `**…**` (Slack→`*`, text/Zalo→strip); nội dung giữ nguyên
    assert "**(1) Tại điều khoản “Phạt 15%”:** vượt trần" in seg and "trái quy định tại Điều 301" in seg
    assert "**Nội dung hiện tại:** “Bên B chịu phạt 15% giá trị hợp đồng.”" in seg
    assert "**Đề xuất sửa như sau:**" in seg
    assert "**Tiếng Việt:** Mức phạt tối đa 8% phần vi phạm." in seg and "**Tiếng Anh:** Cap 8%." in seg
    assert "**Căn cứ:** Điều 301 LTM 2005 giới hạn 8%." in seg
    assert show_button is False                             # đã có điều khoản mới inline → KHÔNG nút


def test_risk_segments_button_and_suggestion_when_no_counter():
    from legalguard.adapters.inbound.channels import _risk_segments
    _num, _idx, _clause, seg, show_button = _risk_segments(_counter_result())[1]
    assert "(2) Tại điều khoản “Thanh toán 90 ngày”" in seg and "**Đề xuất sửa:** rút về 30-45 ngày." in seg
    assert "Đề xuất sửa như sau:" not in seg                # không song ngữ → không có khối này
    assert show_button is True                              # chưa có counter → cần nút


def test_analysis_blocks_always_button_confirm_or_draft():
    # MỌI rủi ro có nút NHÃN NHẤT QUÁN 'Đồng ý sửa'; hành vi khác nhau qua value: có inline → confirm=1
    # (ghi nhận); chưa có → soạn.
    from legalguard.adapters.inbound.channels import _analysis_blocks
    blocks = _analysis_blocks(_counter_result(), "case1")
    btns = [el for b in blocks if b["type"] == "actions" for el in b["elements"]]   # nút ở actions block dưới
    assert len(btns) == 2                                   # cả 2 rủi ro đều có nút
    assert all(b["text"]["text"] == "Đồng ý sửa" for b in btns)   # nhãn NHẤT QUÁN
    assert json.loads(btns[0]["value"]) == {"c": "case1", "i": 0, "confirm": 1}   # rủi ro 1 (inline) → ghi nhận
    assert json.loads(btns[1]["value"]) == {"c": "case1", "i": 1}                 # rủi ro 2 (chưa có) → soạn
    assert "*Tiếng Việt:* Mức phạt tối đa 8%" in json.dumps(blocks, ensure_ascii=False)  # slackify **→*


def test_confirm_amend_records_event_without_llm():
    # Nút 'Xác nhận áp dụng' → CHỈ ghi event agreed_fix + báo nhận, KHÔNG gọi draft_counter_clause (LLM).
    from legalguard.adapters.inbound.channels import _confirm_amend
    from legalguard.domain.models import AnalysisCase
    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[{"clause": "Phạt 15%", "risk": "vượt trần"}], fallbacks=[], trace=[])

    class _Svc:
        def __init__(self):
            self.outcomes = []
            self.drafted = False

        def get_case(self, cid):
            return case if cid == "c1" else None

        def record_outcome(self, o):
            self.outcomes.append(o)

        def draft_counter_clause(self, **kw):
            self.drafted = True
            return {}

    svc, sender = _Svc(), _FakeSender()
    _confirm_amend(svc, sender, "default", "c1", 0, "C1", "th1")
    assert svc.drafted is False                             # KHÔNG gọi LLM
    assert len(svc.outcomes) == 1 and svc.outcomes[0].result == "agreed_fix"
    assert svc.outcomes[0].clause == "Phạt 15%"
    assert "đồng ý sửa" in sender.sent[-1][1].lower() and sender.threads[-1] == "th1"


def test_format_amend_bilingual_and_framework_flag():
    from legalguard.adapters.inbound.channels import _format_amend
    # nguyên văn điều khoản CŨ (trích HĐ) → điều khoản MỚI song ngữ
    out = _format_amend("Phạt 15%", "Bên A chịu phạt 15% giá trị hợp đồng nếu giao chậm.",
                        {"vi": "Mức phạt tối đa 8%.", "en": "Cap 8%.", "grounded": True})
    assert "Phạt 15%" in out and "Điều khoản hiện tại (trích hợp đồng):" in out
    assert "Bên A chịu phạt 15%" in out and "Mức phạt tối đa 8%" in out and "Cap 8%" in out and "AI" in out
    # thiếu evidence (original == clause) → không lặp dòng "hiện tại"
    out2 = _format_amend("X", "X", {"vi": "y", "en": "", "grounded": False})
    assert "khung sơ bộ" in out2 and "Điều khoản hiện tại" not in out2


def test_with_ai_disclosure_idempotent():
    # Công bố AI chỉ xuất hiện ĐÚNG 1 lần dù text đã có sẵn (LLM tự thêm / nối trùng) — fix lặp câu 2 lần.
    from legalguard.adapters.inbound.channels import _AI_DISCLOSURE_LEGAL, _with_ai_disclosure
    disc = _AI_DISCLOSURE_LEGAL.strip()
    assert _with_ai_disclosure("nội dung").count(disc) == 1          # chưa có → thêm 1
    assert _with_ai_disclosure("nội dung" + _AI_DISCLOSURE_LEGAL).count(disc) == 1   # đã có 1 → vẫn 1
    twice = "nội dung" + _AI_DISCLOSURE_LEGAL + _AI_DISCLOSURE_LEGAL
    assert _with_ai_disclosure(twice).count(disc) == 1              # đã có 2 → gộp còn 1


def test_format_amend_no_double_disclosure_when_cc_contains_it():
    # cc.vi lỡ chứa công bố AI (LLM tự thêm) → output KHÔNG lặp công bố 2 lần.
    from legalguard.adapters.inbound.channels import _AI_DISCLOSURE_LEGAL, _format_amend
    disc = _AI_DISCLOSURE_LEGAL.strip()
    out = _format_amend("Phạt 15%", "Bên A chịu phạt 15%.",
                        {"vi": "Mức phạt tối đa 8%." + _AI_DISCLOSURE_LEGAL, "en": "Cap 8%.", "grounded": True})
    assert out.count(disc) == 1


def test_risk_segments_strips_disclosure_from_counter():
    # counter_clause.vi lỡ chứa công bố AI → segment KHÔNG nhúng nó (context block riêng đã có 1 lần).
    from legalguard.adapters.inbound.channels import _AI_DISCLOSURE_LEGAL, _risk_segments
    res = AnalysisResult(
        tenant="VN", risks=[{"clause": "Phạt 15%", "risk": "vượt trần", "evidence": "Bên A phạt 15%.",
                             "counter_clause": {"vi": "Mức phạt tối đa 8%." + _AI_DISCLOSURE_LEGAL, "en": ""}}],
        fallbacks=[], needs_human_review=False, review_reasons=[], summary="", trace=[])
    seg = _risk_segments(res)[0][3]
    assert _AI_DISCLOSURE_LEGAL.strip() not in seg and "Mức phạt tối đa 8%" in seg


def test_run_amend_drafts_and_posts_into_thread():
    from legalguard.adapters.inbound.channels import _run_amend
    from legalguard.domain.models import AnalysisCase
    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[{"clause": "Phạt 15%", "risk": "vượt trần", "legal_basis": "Điều 301",
                                "evidence": "Bên A chịu phạt 15% giá trị hợp đồng nếu giao chậm."}],
                        fallbacks=[{"clause": "Phạt 15%", "suggestion": "giảm về 8%"}], trace=[])

    class _Svc:
        def __init__(self):
            self.called = {}
            self.outcomes = []
        def get_case(self, cid): return case if cid == "c1" else None
        def record_outcome(self, o): self.outcomes.append(o)
        def draft_counter_clause(self, **kw):
            self.called = kw
            return {"vi": "Mức phạt tối đa 8%.", "en": "Cap penalty at 8%.", "grounded": True}

    svc, sender = _Svc(), _FakeSender()
    _run_amend(svc, sender, "default", "c1", 0, "C1", "th1")
    # LLM nhận NGUYÊN VĂN điều khoản gốc (evidence) để viết lại chính đoạn đó
    assert svc.called["clause"] == "Bên A chịu phạt 15% giá trị hợp đồng nếu giao chậm."
    assert svc.called["suggestion"] == "giảm về 8%" and svc.called["legal_basis"] == "Điều 301"
    out = sender.sent[-1][1]
    assert "Điều khoản hiện tại (trích hợp đồng):" in out and "Bên A chịu phạt 15%" in out
    assert "Mức phạt tối đa 8%" in out and "Cap penalty at 8%" in out
    assert sender.threads[-1] == "th1"                     # gửi ĐÚNG thread
    # EVENT "đã đồng ý sửa" được LƯU (result=agreed_fix, đúng clause/org/case) — không lọt win-rate
    assert len(svc.outcomes) == 1
    ev = svc.outcomes[0]
    assert ev.result == "agreed_fix" and ev.clause == "Phạt 15%" and ev.org_id == "default" \
        and ev.case_id == "c1"


def test_run_amend_missing_case_notifies():
    from legalguard.adapters.inbound.channels import _run_amend

    class _Svc:
        def get_case(self, cid): return None

    sender = _FakeSender()
    _run_amend(_Svc(), sender, "default", "nope", 0, "C1", None)
    assert sender.sent and "hồ sơ" in sender.sent[-1][1].lower()


def test_run_amend_wrong_org_blocked():
    from legalguard.adapters.inbound.channels import _run_amend
    from legalguard.domain.models import AnalysisCase
    case = AnalysisCase(id="c1", org_id="default", tenant="VN", created_at="t", lang="vi",
                        contract_excerpt="", summary="", needs_human_review=False,
                        risks=[{"clause": "X", "risk": "y"}], fallbacks=[], trace=[])

    class _Svc:
        def get_case(self, cid): return case
        def draft_counter_clause(self, **kw): raise AssertionError("không được soạn khi sai org")

    sender = _FakeSender()
    _run_amend(_Svc(), sender, "other-org", "c1", 0, "C1", None)   # sai org → chặn, KHÔNG soạn
    assert sender.sent                                    # có báo (không im lặng)


def test_slack_interaction_amend_ok_spawns_run():
    sender = _FakeSender()
    c = _client(slack="sek", slack_sender=sender)
    r = _slack_interaction(c, "sek", "amend_ok", json.dumps({"c": "nocase", "i": 0}),
                           extra={"container": {"thread_ts": "th9"}, "message": {"ts": "m1"}})
    assert r.status_code == 200 and r.json() == {"ok": True}   # không có blocks/block_id → giữ nguyên tin
    # background _run_amend chạy: case không tồn tại (stub) → báo vào ĐÚNG thread th9
    assert sender.sent and sender.threads[-1] == "th9"


def test_slack_interaction_amend_ok_marks_button_agreed_in_place():
    # Bấm 'Đồng ý sửa' → tin gốc cập nhật: nút biến thành '*Đã đồng ý sửa*' TẠI CHỖ (replace_original).
    sender = _FakeSender()
    c = _client(slack="sek", slack_sender=sender)
    blocks = [
        {"type": "section", "block_id": "lg_amend_1", "text": {"type": "mrkdwn", "text": "(1) rủi ro"}},
        {"type": "actions", "block_id": "lg_amend_1_act",
         "elements": [{"type": "button", "action_id": "amend_ok", "value": "{}"}]},
    ]
    val = json.dumps({"c": "nocase", "i": 0, "confirm": 1})
    r = _slack_interaction(c, "sek", "amend_ok", val, extra={
        "container": {"thread_ts": "th9"}, "message": {"ts": "m1", "blocks": blocks},
        "actions": [{"action_id": "amend_ok", "block_id": "lg_amend_1_act", "value": val}]})
    body = r.json()   # KHÔNG có response_url → fallback trả trực tiếp
    assert body.get("replace_original") is True
    assert body["blocks"][1]["type"] == "section"                      # actions → section nổi bật (nút biến mất)
    assert "Đã đồng ý sửa" in body["blocks"][1]["text"]["text"] and "✅" in body["blocks"][1]["text"]["text"]


def test_slack_interaction_amend_ok_updates_via_response_url(monkeypatch):
    # CÓ response_url → cập nhật tin QUA response_url (tin cậy cho blocks); HTTP response chỉ ack {"ok": True}.
    import httpx
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured["url"], captured["body"] = url, json
        class _R:
            status_code = 200
        return _R()
    monkeypatch.setattr(httpx, "post", _fake_post)
    c = _client(slack="sek", slack_sender=_FakeSender())
    blocks = [
        {"type": "section", "block_id": "lg_amend_1", "text": {"type": "mrkdwn", "text": "(1)"}},
        {"type": "actions", "block_id": "lg_amend_1_act",
         "elements": [{"type": "button", "action_id": "amend_ok", "value": "{}"}]},
    ]
    val = json.dumps({"c": "nocase", "i": 0, "confirm": 1})
    r = _slack_interaction(c, "sek", "amend_ok", val, extra={
        "container": {"thread_ts": "th9"}, "message": {"ts": "m1", "blocks": blocks},
        "response_url": "https://hooks.slack.test/xxx",
        "actions": [{"action_id": "amend_ok", "block_id": "lg_amend_1_act", "value": val}]})
    assert r.json() == {"ok": True}                                    # HTTP chỉ ack
    assert captured["url"] == "https://hooks.slack.test/xxx"           # cập nhật đi qua response_url
    assert captured["body"]["replace_original"] is True and captured["body"]["text"] == "Đã đồng ý sửa"
    assert captured["body"]["blocks"][1]["type"] == "section"
    assert "Đã đồng ý sửa" in captured["body"]["blocks"][1]["text"]["text"]


def test_reply_ex_marks_lookup_and_analysis_kind():
    h = _handler()
    assert h.reply_ex("cK", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu?").kind == "lookup"
    assert h.reply_ex("cA", text=MSG).kind == "analysis"


# ---- Phase 0: persist-first (lưu tin dù lỗi/retry — dữ liệu, KHÔNG hiển thị lại) ----
def test_user_message_persisted_before_handle():
    import pytest
    h = _handler()
    h._handle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LLM down"))  # ép lỗi giữa chừng
    with pytest.raises(RuntimeError):
        h.reply_ex("slack:c:p0a", text="Mức phạt vi phạm hợp đồng tối đa bao nhiêu?")
    conv = h.store.get("slack:c:p0a")
    assert conv and conv.history and conv.history[-1]["role"] == "user"    # tin user VẪN bền
    assert all(m["role"] != "assistant" for m in conv.history)             # mồ côi = dấu vết lỗi auditable


def test_no_duplicate_user_turn_on_retry():
    import pytest
    h = _handler()
    orig, calls = h._handle, {"n": 0}
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return orig(*a, **k)
    h._handle = flaky
    msg = "Mức phạt vi phạm hợp đồng tối đa bao nhiêu?"
    with pytest.raises(RuntimeError):
        h.reply_ex("slack:c:p0b", text=msg)      # lần 1 lỗi → orphan user turn
    h.reply_ex("slack:c:p0b", text=msg)          # retry cùng text → KHÔNG dup user turn
    conv = h.store.get("slack:c:p0b")
    assert [m["role"] for m in conv.history] == ["user", "assistant"]   # đúng 1 user + 1 reply


def test_distinct_resend_after_reply_keeps_both_turns():
    # Rule dedup HẸP: chỉ chặn khi turn cuối là user-orphan. Gửi lại SAU khi đã có reply = lượt mới hợp lệ.
    h = _handler()
    msg = "Mức phạt vi phạm hợp đồng tối đa bao nhiêu?"
    h.reply_ex("slack:c:p0c", text=msg)
    h.reply_ex("slack:c:p0c", text=msg)
    conv = h.store.get("slack:c:p0c")
    assert [m["role"] for m in conv.history] == ["user", "assistant", "user", "assistant"]


def _retry_id_from_blocks(blocks):
    for b in blocks or []:
        if b.get("type") == "actions":
            for el in b["elements"]:
                if el.get("action_id") == "retry_run":
                    return json.loads(el["value"])["k"]
    return None


# ---- Phase 1: nút 🔁 Thử lại khi lỗi (Slack) ----
def test_retry_store_ttl_and_pop_once(monkeypatch):
    from legalguard.adapters.inbound import channels as ch
    store = ch._RetryStore()
    store.put("k", ("to", "txt", None, None, "th"))
    assert store.pop("k") == ("to", "txt", None, None, "th")   # lấy đúng payload
    assert store.pop("k") is None                               # one-shot (đã pop)
    store.put("k2", ("to", "txt", None, None, "th"))
    monkeypatch.setattr(ch.time, "monotonic", lambda: 10 ** 9)  # nhảy quá TTL
    assert store.pop("k2") is None                              # hết hạn → None


def test_process_failure_offers_retry_button():
    from legalguard.adapters.inbound.channels import _process, _retry_store
    h = _handler()
    h.reply_ex = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    s = _FakeSender()
    _process(h, s, "slack:C1:r1", "C1", "Mức phạt vi phạm hợp đồng tối đa?",
             None, None, "t1", 10 * 1024 * 1024, True)
    rid = _retry_id_from_blocks(s.blocks)                       # retry_id = uuid trong value nút
    assert rid                                                  # có nút 🔁
    payload = _retry_store.pop(rid)
    assert payload and payload[0] == "slack:C1:r1"             # payload lưu conv_key ĐẦU (để _process dùng đúng)


def test_zalo_failure_no_retry_button_unchanged():
    from legalguard.adapters.inbound.channels import _process
    h = _handler()
    h.reply_ex = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    s = _FakeSender()
    _process(h, s, "zalo:U1", "U1", "Mức phạt vi phạm hợp đồng?",
             None, None, None, 10 * 1024 * 1024, False)   # supports_buttons=False (Zalo)
    assert s.blocks is None and "có lỗi" in s.sent[-1][1]        # reply text cũ, KHÔNG nút


def test_interactions_retry_spawns_process():
    from legalguard.adapters.inbound.channels import _retry_store
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _retry_store.put("rid-r2", ("slack:C1:r2", "C1", "Mức phạt vi phạm hợp đồng tối đa?", None, None, "t2"))
    r = _slack_interaction(c, "s", "retry_run", json.dumps({"k": "rid-r2"}))
    assert r.status_code == 200 and "Đang thử lại" in r.json()["text"]
    assert sender.sent                                          # background _process đã chạy + gửi reply


def test_interactions_retry_expired():
    c = _client(slack="s", slack_sender=_FakeSender())
    r = _slack_interaction(c, "s", "retry_run", json.dumps({"k": "slack:C1:khong-ton-tai"}))
    assert r.status_code == 200 and "hết hạn" in r.json()["text"]


# ---- Phase 2: sửa tin CÂU TRA CỨU → tự chạy lại ----
def _edit_event(channel, ts, new_text, prev_text, edited_ts="e1", bot=False):
    inner = {"text": new_text, "ts": ts, "edited": {"ts": edited_ts}}
    if bot:
        inner["bot_id"] = "B1"
    return {"event": {"type": "message", "subtype": "message_changed", "channel": channel,
                      "message": inner, "previous_message": {"text": prev_text}, "event_ts": "ev1"}}


def test_edited_lookup_question_reruns_with_prefix():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", _edit_event("C1", "100.1", "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?",
                                    "Mức phạt vi phạm hợp đồng?"))
    assert sender.sent and sender.sent[-1][1].startswith("_(Cập nhật theo tin đã sửa)")   # chạy lại, đánh dấu cập nhật


def test_edited_unfurl_same_text_ignored():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", _edit_event("C1", "100.2", "Mức phạt vi phạm hợp đồng?",
                                    "Mức phạt vi phạm hợp đồng?"))    # text KHÔNG đổi (unfurl)
    assert sender.sent == []                                          # bỏ qua


def test_edited_contract_message_ignored():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", _edit_event("C1", "100.3", MSG + " sửa thêm", MSG))   # đoạn HĐ, không phải câu hỏi
    assert sender.sent == []                                          # không chạy lại (tránh mutate deal)


def test_edited_by_bot_ignored():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    _slack_post(c, "s", _edit_event("C1", "100.4", "Mức phạt vi phạm hợp đồng tối đa %?",
                                    "cũ", bot=True))
    assert sender.sent == []


def test_edit_dedup_same_edited_ts():
    sender = _FakeSender()
    c = _client(slack="s", slack_sender=sender)
    ev = _edit_event("C1", "100.5", "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?", "cũ", edited_ts="e9")
    _slack_post(c, "s", ev)
    _slack_post(c, "s", ev)                                           # cùng edited.ts → chỉ xử lý 1 lần
    reruns = [t for _, t in sender.sent if t.startswith("_(Cập nhật theo tin đã sửa)")]   # đếm REPLY rerun (bỏ ack)
    assert len(reruns) == 1


# ---- Cải tiến: nút 🔁 cho lỗi TẢI FILE (transient); file quá lớn KHÔNG nút (thử lại vô ích) ----
def test_file_download_failure_offers_retry():
    from legalguard.adapters.inbound.channels import _process, _retry_store
    class _BoomSender(_FakeSender):
        def download(self, url):
            raise RuntimeError("net down")
    s = _BoomSender()
    _process(_handler(), s, "slack:C1:dl", "C1", "", "https://files/x", "hd.pdf",
             "t", 10 * 1024 * 1024, True)
    rid = _retry_id_from_blocks(s.blocks)
    assert rid                                                                          # có nút 🔁
    payload = _retry_store.pop(rid)
    assert payload and payload[0] == "slack:C1:dl" and payload[3] == "https://files/x"  # conv_key + file_url lưu
    assert "không tải được" in s.sent[-1][1]


def test_file_too_large_no_retry_button():
    from legalguard.adapters.inbound.channels import _process
    s = _FakeSender(file_bytes=b"x" * 4096)          # 4KB > max 1KB
    _process(_handler(), s, "slack:C1:big", "C1", "", "https://files/x", "hd.pdf", "t", 1024, True)
    assert s.blocks is None and "quá lớn" in s.sent[-1][1]   # lỗi cố định → KHÔNG nút thử lại


# ---- Review fixes: follow-up không lặp câu hỏi (persist-first) + retry_id riêng mỗi lỗi ----
def test_followup_prompt_does_not_duplicate_current_question():
    h = _handler()
    h.reply("cFU", text=MSG)                                  # analyze → set context (deal)
    cap = {}
    h.service.reasoner.complete = lambda p, *a, **k: cap.setdefault("p", p) or "ok"
    q = "Nếu đối tác từ chối thì mình nên làm gì?"            # follow-up (không lookup/counter)
    h.reply_ex("cFU", text=q)
    assert "p" in cap and cap["p"].count(q) == 1              # câu hỏi hiện tại CHỈ 1 lần (không lặp trong hist)


def test_two_failures_same_thread_distinct_retry_ids():
    from legalguard.adapters.inbound.channels import _process, _retry_store
    h = _handler()
    h.reply_ex = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    key = "slack:C1:th"
    s1, s2 = _FakeSender(), _FakeSender()
    _process(h, s1, key, "C1", "Mức phạt vi phạm hợp đồng A?", None, None, "th", 10 * 1024 * 1024, True)
    _process(h, s2, key, "C1", "Mức phạt vi phạm hợp đồng B?", None, None, "th", 10 * 1024 * 1024, True)
    rid1, rid2 = _retry_id_from_blocks(s1.blocks), _retry_id_from_blocks(s2.blocks)
    assert rid1 and rid2 and rid1 != rid2                     # 2 lỗi cùng thread → retry_id RIÊNG (không ghi đè)
    p1, p2 = _retry_store.pop(rid1), _retry_store.pop(rid2)
    assert p1[2] == "Mức phạt vi phạm hợp đồng A?" and p2[2] == "Mức phạt vi phạm hợp đồng B?"


# ---- MENTION GATE (M1): chỉ trả lời khi @bot hoặc DM ----
def _mention_client(sender):
    handler = _handler()
    app = FastAPI()
    app.include_router(build_channels_router(handler, slack_signing_secret="s",
                                             slack_sender=sender, mention_only=True))
    return TestClient(app)


def _auth(payload):
    payload["authorizations"] = [{"user_id": "UBOT"}]
    return payload


def test_gate_channel_message_without_mention_silent():
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "g1.1",
                                         "text": "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.sent == []                       # không mention → IM LẶNG tuyệt đối (không cả ack)


def test_gate_mention_other_user_silent():
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "g1.2",
                                         "text": "<@UKHAC> mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.sent == []                       # mention NGƯỜI KHÁC → vẫn im lặng


def test_gate_mention_bot_processed():
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "g1.3",
                                         "text": "<@UBOT> Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.sent                             # có mention bot → xử lý


def test_gate_app_mention_processed():
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "app_mention", "channel": "C1", "ts": "g1.4",
                                         "text": "<@UBOT> Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.sent


def test_gate_dm_without_mention_processed():
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "D1", "channel_type": "im",
                                         "ts": "g1.5",
                                         "text": "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.sent                             # DM → miễn mention


def test_gate_edited_message_requires_mention():
    sender = _FakeSender()
    c = _mention_client(sender)
    ev = _edit_event("C1", "g1.6", "Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?", "cũ")
    _slack_post(c, "s", _auth(ev))                 # tin sửa KHÔNG mention → bỏ qua
    assert sender.sent == []
    ev2 = _edit_event("C1", "g1.7", "<@UBOT> Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?", "cũ")
    _slack_post(c, "s", _auth(ev2))                # tin sửa CÓ mention → rerun
    assert any(t.startswith("_(Cập nhật") for _, t in sender.sent)


# ---- M2: catch-up thread khi mention giữa hội thoại ----
def test_mention_mid_thread_fetches_context():
    msgs = [{"user": "U1", "text": "HĐ phạt 15% nếu giao chậm", "ts": "1.0"},
            {"user": "U2", "text": "vậy có vượt trần không nhỉ", "ts": "1.1"},
            {"user": "U1", "text": "<@UBOT> ý bạn thế nào về đoạn trên", "ts": "1.2"}]
    sender = _FakeSender(thread_msgs=msgs)
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "1.2",
                                         "thread_ts": "1.0",
                                         "text": "<@UBOT> ý bạn thế nào về đoạn trên"}}))
    assert sender.fetched == [("C1", "1.0")]       # đọc ĐÚNG thread gốc
    assert sender.sent                             # có trả lời (stub reasoner)


def test_mention_at_root_no_fetch():
    sender = _FakeSender(thread_msgs=[{"user": "U1", "text": "x", "ts": "2.0"}])
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "2.0",
                                         "text": "<@UBOT> Mức phạt vi phạm hợp đồng tối đa bao nhiêu %?"}}))
    assert sender.fetched == []                    # tin gốc (không trong thread) → khỏi fetch


def test_build_thread_context_roles_redact_dedup():
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": "hợp đồng phạt 15%, mail tôi ab@x.vn", "ts": "1"},
            {"user": "UBOT", "text": "Đã ghi nhận.", "ts": "2"},
            {"user": "UB2", "bot_id": "B9", "text": "tin bot khác", "ts": "3"},
            {"user": "U2", "text": "đã có trong history", "ts": "4"}]
    out = _build_thread_context(msgs, "UBOT", known={"đã có trong history"})
    assert "Người A: hợp đồng phạt 15%" in out and "ab@x.vn" not in out     # nhãn speaker + redact PII
    assert "trợ lý: Đã ghi nhận." in out                                     # tin bot mình = trợ lý
    assert "tin bot khác" not in out and "đã có trong history" not in out    # bỏ bot khác + dedup


def test_build_thread_context_budget_keeps_head_tail():
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": f"tin số {i} " + "x" * 200, "ts": str(i)} for i in range(100)]
    out = _build_thread_context(msgs, "UBOT", limit=2000)
    assert len(out) <= 2100 and "tin số 0 " in out and "tin số 99 " in out  # giữ đầu + đuôi
    assert "…(đã lược tin không liên quan)…" in out


# ---- M4: thread NHIỀU NGƯỜI — ai-nói-gì + lọc liên quan ----
def test_multiuser_labels_names_and_asker():
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": "hợp đồng phạt 15%", "ts": "1"},
            {"user": "U2", "text": "khoản này cao đấy", "ts": "2"},
            {"user": "U3", "text": "đồng ý sửa về 8%", "ts": "3"}]
    # Có tên thật → dùng tên; asker được đánh dấu (người hỏi).
    out = _build_thread_context(msgs, "UBOT", names={"U1": "An", "U2": "Bình"}, asker_id="U2")
    assert "Người tham gia: An, Bình (người hỏi), Người C" in out            # U3 không resolve → nhãn
    assert "An: hợp đồng phạt 15%" in out and "Bình: khoản này cao" in out
    # Không tên → nhãn ẩn danh ổn định theo thứ tự xuất hiện.
    out2 = _build_thread_context(msgs, "UBOT")
    assert "Người A: hợp đồng phạt 15%" in out2 and "Người B: khoản này cao" in out2


def test_multiuser_comention_preserved():
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": "Điều 5 phạt 15%", "ts": "1"},
            {"user": "U2", "text": "<@UBOT> hỏi ý <@U1> về mức phạt, cả <@U9> nữa", "ts": "2"}]
    out = _build_thread_context(msgs, "UBOT", names={"U1": "An"})
    assert "hỏi ý @An về mức phạt" in out                 # co-mention giữ referent (tên thật)
    assert "@người khác" in out                           # mention user ngoài thread, không tên
    assert "<@UBOT>" not in out and "<@U1>" not in out    # tag thô không lọt vào prompt


def test_multiuser_relevance_selection_drops_chitchat():
    from legalguard.adapters.inbound.channels import _build_thread_context
    pad = "x" * 150
    msgs = ([{"user": "U1", "text": "Hợp đồng: Điều 5 phạt vi phạm 15% nếu giao chậm " + pad, "ts": "0"}]
            + [{"user": "U2", "text": f"trưa nay ăn bún chả không {i} " + pad, "ts": str(i)}
               for i in range(1, 20)]
            + [{"user": "U1", "text": "đối tác gửi phụ lục bảo hành 6 tháng " + pad, "ts": "20"}]
            + [{"user": "U2", "text": f"chuyện phiếm cuối {i} " + pad, "ts": str(i)}
               for i in range(21, 26)])
    q = "chốt mức phạt với thời hạn bảo hành thế nào?"
    out = _build_thread_context(msgs, "UBOT", limit=1600, question=q)
    assert "phạt vi phạm 15%" in out                      # tin đầu (chủ đề) luôn giữ
    assert "bảo hành 6 tháng" in out                      # tin GIỮA liên quan được chọn (lexical)
    assert "…(đã lược tin không liên quan)…" in out       # có lược
    assert out.count("bún chả") <= 2                      # chuyện phiếm giữa thread bị bỏ gần hết


def test_multiuser_rank_fn_semantic_priority():
    from legalguard.adapters.inbound.channels import _build_thread_context
    pad = "y" * 150
    msgs = ([{"user": "U1", "text": "chủ đề gốc " + pad, "ts": "0"}]
            + [{"user": "U2", "text": f"tin giữa số {i} " + pad, "ts": str(i)} for i in range(1, 20)])

    def rank(q, texts):                                   # semantic giả: 'số 7' liên quan nhất
        return [10.0 if "số 7 " in t else 0.1 for t in texts]

    out = _build_thread_context(msgs, "UBOT", limit=1200, question="câu hỏi bất kỳ", rank_fn=rank)
    assert "tin giữa số 7 " in out                        # semantic chọn đúng tin
    assert "chủ đề gốc" in out and "tin giữa số 19" in out  # đầu + đuôi vẫn giữ


def test_relevance_scores_three_tiers():
    from legalguard.adapters.inbound.channels import _relevance_scores
    texts = ["bàn về mức phạt hợp đồng", "trưa ăn gì", "phạt vi phạm 8%"]
    assert _relevance_scores("q", texts, rank_fn=lambda q, t: [1, 2, 3]) == [1.0, 2.0, 3.0]

    def boom(q, t):                                       # tầng 1 lỗi → lexical
        raise RuntimeError("api down")

    lex = _relevance_scores("mức phạt vi phạm", texts, rank_fn=boom)
    assert lex[0] > lex[1] and lex[2] > lex[1]
    assert _relevance_scores("ơi?", texts) == [0.0, 1.0, 2.0]   # không token đặc trưng → recency


def test_short_thread_kept_fully_no_marker():
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": f"tin {i} nội dung", "ts": str(i)} for i in range(8)]
    out = _build_thread_context(msgs, "UBOT", question="hỏi gì đó")
    assert all(f"tin {i} nội dung" in out for i in range(8))   # vừa budget → giữ 100%
    assert "…(đã lược" not in out


def test_process_resolves_names_and_passes_asker():
    # _process: resolve_names=True → gọi sender.resolve_names với user NÓI + user được CO-MENTION
    # (không gồm bot), rồi truyền names + asker_id vào reply_ex.
    from legalguard.adapters.inbound.channels import ChatReply, _process
    msgs = [{"user": "U1", "text": "nội dung về hợp đồng phạt", "ts": "1"},
            {"user": "U2", "text": "nhắc <@U9> xem nhé", "ts": "2"}]

    class _NameSender(_FakeSender):
        def __init__(self):
            super().__init__(thread_msgs=msgs)
            self.resolved = []

        def resolve_names(self, ids):
            self.resolved.append(list(ids))
            return {"U1": "An"}

    class _H:
        def __init__(self):
            self.kw = None

        def reply_ex(self, key, **kw):
            self.kw = kw
            return ChatReply("ok", "", "")

    s, h = _NameSender(), _H()
    _process(h, s, "k", "C1", "câu hỏi", None, None, "th", 10 * 1024 * 1024, True,
             thread_fetch=("C1", "1.0"), bot_uid="UBOT", asker_id="U2", resolve_names=True)
    assert s.resolved and set(s.resolved[0]) == {"U1", "U2", "U9"}   # nói + co-mention, KHÔNG gồm bot
    assert h.kw["names"] == {"U1": "An"} and h.kw["asker_id"] == "U2"


# ---- M3: đọc thread từ permalink ----
def test_parse_permalink_variants():
    from legalguard.adapters.inbound.channels import _parse_permalink
    ch, root, _ = _parse_permalink("xem https://acme.slack.com/archives/C0AB1/p1720512345678901 nhé")
    assert ch == "C0AB1" and root == "1720512345.678901"
    ch2, root2, _ = _parse_permalink(
        "<https://a.slack.com/archives/C9/p1720512345678901?thread_ts=1720512000.000100&cid=C9|link>")
    assert ch2 == "C9" and root2 == "1720512000.000100"       # link reply → root = thread_ts
    assert _parse_permalink("không có link") is None


def test_mention_with_link_same_channel_fetches_that_thread():
    msgs = [{"user": "U1", "text": "nội dung thread cũ về hợp đồng", "ts": "9.0"}]
    sender = _FakeSender(thread_msgs=msgs)
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C0AB1", "ts": "9.9",
        "text": "<@UBOT> tóm tắt giúp <https://acme.slack.com/archives/C0AB1/p1720512345678901>"}}))
    assert sender.fetched == [("C0AB1", "1720512345.678901")]   # fetch đúng thread từ link
    assert sender.sent                                          # có trả lời


def test_mention_with_link_other_channel_refused():
    sender = _FakeSender(thread_msgs=[{"user": "U1", "text": "bí mật", "ts": "1"}])
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "CKHAC", "ts": "9.8",
        "text": "<@UBOT> đọc giúp <https://acme.slack.com/archives/C0AB1/p1720512345678901>"}}))
    assert sender.fetched == []                                 # KHÔNG fetch kênh khác (privacy V1)
    assert sender.sent and "quyền riêng tư" in sender.sent[-1][1]


def test_mention_with_link_unreadable_thread_notifies():
    sender = _FakeSender(thread_msgs=[])                        # fetch trả rỗng (not_in_channel…)
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C0AB1", "ts": "9.7",
        "text": "<@UBOT> tóm tắt <https://acme.slack.com/archives/C0AB1/p1720512345678901>"}}))
    assert sender.sent and "Chưa đọc được thread" in sender.sent[-1][1]


def test_thread_context_legal_question_uses_followup_not_lookup():
    # Finding #1: câu hỏi LUẬT giữa thread (có ? + thuật ngữ) mà CÓ thread_context → phải trả lời THEO
    # NGỮ CẢNH (followup), KHÔNG rơi vào lookup (sẽ vứt thread_context).
    from legalguard.domain.models import Conversation
    h = _handler()
    calls = []
    h._followup = lambda conv, q, lang, tc="": calls.append(("followup", tc)) or "FU"
    h.service.lookup = lambda *a, **k: calls.append(("lookup", None)) or ("LK", [])
    h._handle(Conversation(id="t"), "phạt vi phạm hợp đồng tối đa bao nhiêu %?", None, None, "vi",
              thread_context="người dùng: bàn về hợp đồng phạt 15% nếu giao chậm")
    assert calls and calls[0][0] == "followup"                 # KHÔNG gọi lookup
    assert "phạt 15%" in calls[0][1]                           # thread_context được truyền vào


def test_gate_gated_message_does_not_poison_dedup_for_app_mention():
    # Finding #2: bot_uid rỗng (thiếu authorizations) — event `message` bị gate loại KHÔNG được ăn slot
    # dedup, để `app_mention` cùng ts (qua gate) vẫn được xử lý (mention thật không bị nuốt oan).
    sender = _FakeSender()
    c = _mention_client(sender)
    q = "<@UBOT> mức phạt vi phạm hợp đồng thương mại tối đa bao nhiêu %?"
    _slack_post(c, "s", {"event": {"type": "message", "channel": "C1", "ts": "z2", "text": q}})
    assert sender.sent == []                                    # message + bot_uid rỗng → gate loại
    _slack_post(c, "s", {"event": {"type": "app_mention", "channel": "C1", "ts": "z2", "text": q}})
    assert sender.sent                                          # app_mention cùng ts vẫn được trả lời


def test_thread_context_instruction_with_signal_word_not_analyzed_as_contract():
    # Live test C: mention giữa thread + chỉ dẫn có từ khóa HĐ ("điều khoản/mức phạt") nhưng KHÔNG phải
    # HĐ mới → phải đi followup-theo-ngữ-cảnh, KHÔNG bị nhánh phân tích HĐ bắt.
    from legalguard.domain.models import Conversation
    h = _handler()
    calls = []
    h._followup = lambda conv, q, lang, tc="": calls.append(("followup", tc)) or "FU"
    h.service.analyze = lambda *a, **k: (_ for _ in ()).throw(AssertionError("KHÔNG được analyze"))
    r = h._handle(Conversation(id="t"), "nhận xét giúp về mức phạt ở điều khoản đang bàn phía trên",
                  None, None, "vi", thread_context="người dùng: Điều 5 phạt 15% nếu giao chậm")
    assert r.text == "FU" and calls[0][0] == "followup" and "phạt 15%" in calls[0][1]


def test_build_thread_context_never_exceeds_limit_with_scattered_gaps():
    # Review #1: chọn giữa rải rác (nhiều gap) → output VẪN ≤ limit (vòng trim + reserve marker).
    from legalguard.adapters.inbound.channels import _build_thread_context
    pad = "z" * 120
    # câu hỏi khớp rải rác các tin lẻ ở giữa → nhiều gap
    msgs = [{"user": "U1", "text": "đầu " + pad, "ts": "0"}]
    for i in range(1, 40):
        kw = "phạt vi phạm" if i % 3 == 0 else "chuyện phiếm"
        msgs.append({"user": "U2", "text": f"{kw} {i} " + pad, "ts": str(i)})
    out = _build_thread_context(msgs, "UBOT", limit=1500, question="mức phạt vi phạm là bao nhiêu")
    assert len(out) <= 1500                          # KHÔNG vượt limit dù nhiều gap


def test_build_thread_context_always_keeps_first_even_if_huge():
    # Review #2: tin đầu dài hơn budget → vẫn có mặt (cắt ngắn), KHÔNG bị bỏ.
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": "HỢP ĐỒNG GỐC " + "a" * 5000, "ts": "0"},
            {"user": "U2", "text": "tin ngắn sau", "ts": "1"}]
    out = _build_thread_context(msgs, "UBOT", limit=800)
    assert "HỢP ĐỒNG GỐC" in out and len(out) <= 800   # tin đầu luôn có mặt, vẫn trong limit


def test_header_only_lists_speakers_with_visible_line():
    # Review #4: người chỉ mention bot (dòng rỗng sau strip) / bị dedup → KHÔNG lên header.
    from legalguard.adapters.inbound.channels import _build_thread_context
    msgs = [{"user": "U1", "text": "hợp đồng phạt 15%", "ts": "1"},
            {"user": "U2", "text": "<@UBOT>", "ts": "2"},          # chỉ tag bot → dòng rỗng
            {"user": "U3", "text": "đã có trong history", "ts": "3"}]
    out = _build_thread_context(msgs, "UBOT", known={"đã có trong history"})
    assert "Người A" in out                                        # U1 có tin
    assert "Người B" not in out and "Người C" not in out           # U2 (rỗng) + U3 (dedup) không lên header


def test_gate_mention_with_display_name_variant():
    # Review #5: mention dạng <@BOT|Legal Guard> (có tên) vẫn kích hoạt gate (không im lặng oan).
    sender = _FakeSender()
    c = _mention_client(sender)
    _slack_post(c, "s", _auth({"event": {"type": "message", "channel": "C1", "ts": "v1",
        "text": "<@UBOT|Legal Guard> phạt vi phạm hợp đồng thương mại tối đa bao nhiêu %?"}}))
    assert sender.sent                                             # dạng có |tên vẫn được trả lời
