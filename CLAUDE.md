# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

MVP scaffold exists and runs end-to-end. The Vietnamese planning docs are the source of truth for
scope/strategy (in `docs/internal/`, gitignored — not in the public repo):
`docs/internal/legal-guard.md` (plan + corrected hackathon facts + §5b production architecture),
`docs/internal/phan-tich-kha-thi.md` (feasibility + judge's-eye analysis),
`docs/internal/pitch-presell.md` (sales playbook).

**Open-core boundary** (`docs/OPEN-CORE.md`): engine = MIT public (contest deliverable). MOAT stays
PRIVATE/gitignored — do NOT commit: `knowledge_base/_orgs/<org_id>/*` (deep party-aware tactics, auto-
overlaid by `for_org` in /analyze), `evaluation/_private/` (full lawyer-verified golden), `docs/internal/`,
runtime flywheel data. Public face is **English-first** `README.md` (agent framing for the international
Qwen contest); `README.vi.md` = Vietnamese; `docs/architecture.en.md` = EN agent showcase. The committed
KB (public VN law) + 12-situation `fallback_matrix.md` + sample golden are the PUBLIC baseline. Business
build (post-contest) = a separate private repo: engine + moat data + closed features.

## Commands (managed with `uv`)

```bash
uv sync                            # create .venv + install from pyproject.toml / uv.lock
uv run uvicorn app:app --reload    # run API (http://localhost:8000/docs)
uv run ruff check .                # lint
uv run pytest                      # full suite (offline; conftest blanks API keys → stub mode)
uv run pytest tests/test_agent.py::test_agent_produces_structured_risks_and_trace   # single test
uv run alembic upgrade head        # apply DB migrations (DATABASE_URL; sqlite default, postgres in prod)
uv run python -m evaluation.run_eval  # fast eval: precision/recall + groundedness on golden set (offline)
uv run python -m evaluation.legal_eval # eval TRA CỨU LUẬT: Recall@k/MRR + closure-recall + still-good-law (offline)
uv run python -m evaluation.zalo_ltr_eval # eval trên BENCHMARK CÔNG KHAI Zalo LTR 2021 (MIT, 61k điều/788 query): BM25 lexical Recall@10/MRR@10/Hit@1 → zalo_ltr_report.json (offline sau khi tải HF). LƯU Ý: chỉ đo thành phần lexical, KHÔNG so trực tiếp với accuracy 98% (end-to-end answer trên KB)
uv run python -m evaluation.rerank_ab --reranker qwen3-api [--limit N] # A/B RERANK trên Zalo LTR: BM25 top-N → rerank → đo LIFT MRR@10/Recall@10. Arm qwen3-api chạy ngay (cần key); arm hf:<model> cần GPU (docs/internal/reranker-ab-deploy.md). Đo 2/7 (40 query): qwen3-rerank nâng MRR 0.487→0.622
uv run python -m evaluation.accuracy_eval [--no-write] [--repeat=N] # eval ĐỘ CHÍNH XÁC CÂU TRẢ LỜI (golden đáp-án-đã-biết) → accuracy_report.json cho /trust. --no-write: thí nghiệm không ghi đè report. --repeat=N: majority-vote N lần/ca → số ỔN ĐỊNH + đánh dấu ca FLAKY (chống nhiễu LLM hosted dải 52-54; điều kiện tiên quyết đo được thay đổi nhỏ khi mở rộng KB)
uv run python -m evaluation.nli_eval      # eval RIÊNG judge NLI (16 ca có nhãn + hard negative, flash vs flagship; cần QWEN key) → nli_report.json (đo 2/7: flash 16/16, đồng thuận 100%)
uv run python -m evaluation.fast_ab [--reps 4] [--models flagship,plus,flash] # A/B MODEL cho /analyze mode=fast: bộ HĐ có NHÃN (neo luật VN: phạt>8%/lãi>20%=illegal; 120-ngày/luật-ngoài=unfavorable) → đo illegal_recall / MISS_illegal / over-flag / latency mỗi model × reps (khử nhiễu). Đo 14/7 reps=4: flash 6s recall 87.5% 0 over-flag (mặc định); plus 18s 25% over-flag (bỏ); flagship 72s 0 miss. Cần QWEN key, KHÔNG cần KB → fast_ab_report.json
uv run python -m evaluation.golden_to_review # sinh PHIẾU LUẬT SƯ DUYỆT từ golden → docs/internal/golden-set-lawyer-review.{csv,md} (gửi luật sư xác nhận)
uv run python -m ingestion.hf_to_kb --pages 4 --keyword "hóa đơn" --out knowledge_base/_ingested # ETL sample: HF dataset luật VN → KB .md (front-matter status)
uv run python -m ingestion.hf_to_kb --bulk --limit 2000 --out knowledge_base/_ingested # CON BATCH bulk: ingest toàn bộ th1nhng0 (cần `uv add datasets`) + cạnh đồ thị (amends/replaced_by/guides) + hiệu lực
uv run python -m ingestion.hf_to_kb --bulk --mirror-dir data/legal-corpus-mirror/th1nhng0/data --in-force-only --central-only --types nghi_dinh,thong_tu,luat,phap_lenh --keyword "<domain>" --dry-run # ingest OFFLINE từ mirror + lọc QUY PHẠM (bỏ Quyết định/Chỉ thị nhiễu); --dry-run đếm trước. Quy trình eval-gated: docs/internal/ingest-eval-gated-process.md (BẮT BUỘC đo legal_eval + accuracy_eval trước promote vào KB/VN)
uv run python -m evaluation.feedback_to_golden --org default --out evaluation/golden_candidates.json # vòng học: feedback ⚠️/➖ → ứng viên golden + báo lỗ hổng KB
uv sync --group eval                  # cài lớp eval sâu (RAGAS) — opt-in, không cần cho runtime
uv sync --group export                # cài python-docx cho xuất Word bản-ghi-nhớ (Phase C) — opt-in
uv sync --group ingestion             # cài datasets cho bulk ingest th1nhng0 (--bulk) — opt-in
uv run python -m evaluation.ragas_eval  # deep eval: RAGAS LLM-as-judge (cần QWEN_API_KEY; chậm/tốn call)
uv run python -m evaluation.integration_check  # smoke LLM THẬT (như trên Slack): analyze/lookup/counter… → lưu snapshot.json+md (evaluation/snapshots/) để diff giữa các lần
uv run python -m evaluation.integration_check --compare evaluation/snapshots/<cũ>/snapshot.json  # so nhanh với lần chạy cũ (định tuyến/#risk/độ dài reply)
uv run python -m evaluation.lookup_format_check  # test format+cache lookup nhiều case THẬT (Trả lời/Căn cứ + đo cache)
uv run python -m scripts.slack_smoke   # SMOKE SLACK OFFLINE (không token/mạng): A) xem trước FORMAT blocks (tô đậm) B) định tuyến (app+FakeSender, sự kiện đã ký) C) nút bấm — stub LLM, nhanh/tất định
uv run python -m scripts.slack_live --channel C0XXXX [--thread <ts>] [--only analysis|lookup|amend|heartbeat]  # SMOKE SLACK THẬT: đăng reply mẫu (rà soát/tra cứu/điều khoản sửa/heartbeat) vào kênh để SOI rendering (in đậm/giãn dòng/nút/song ngữ). Cần SLACK_BOT_TOKEN + chat:write, mời bot vào kênh
API_BASE=<url> SLACK_TEST_CHANNEL=C0XXXX uv run python -m scripts.smoke_live [--quick|--no-slack|--no-llm]  # SMOKE E2E trên DEPLOY THẬT (ECS): API (health/ask-B/analyze/counter/negotiate) + Slack thật (event-đã-ký/nút/format A/reformat D/heartbeat). Đọc .env; --quick = chỉ API nhanh
API_BASE=<url> uv run python -m scripts.latency_probe [--only short|med|long]  # ĐO LATENCY THẬT từng bước (agent-loop vs post-agent) trên HĐ ngắn/vừa/dài — cần QWEN key + KB embeddings ẤM
API_BASE=<url> CHANNEL_ID=C0XXXX uv run python -m scripts.cleanup_smoke [--yes]  # DỌN dữ liệu test smoke trên prod (case + tin [SMOKE] Slack); dry-run mặc định, --yes mới xoá; feedback ref='smoke' xoá bằng SQL (in ra lệnh)
uv add <pkg>                       # add a dependency
```

AI/RAG quality techniques: grounding+citation+evidence (`tools.py`), verification 2-layer
(clause-existence + LLM-judge + NLI entailment `nli_supports` — kiểm "nguồn CÓ hậu thuẫn claim không",
chống citation tồn-tại-nhưng-không-hỗ-trợ, `NLI_VERIFICATION`; áp vào legal_basis grounding + lookup,
`domain/verification.py`), **NLI-mâu-thuẫn `nli_contradicts`** (đảo chiều — "điều khoản CÓ TRÁI điều luật
không"; Phase B phát hiện TRÁI LUẬT có grounding, parser CHẶT bất-đối-xứng: NO/KHÔNG→False an toàn, chỉ
'YES' tiếng Anh→True, bỏ 'CÓ' tránh va 'có thể'→illegal sai), lexical BM25 (Okapi, length-norm + IDF) +
embedding, hybrid retrieval RRF + opt-in LLM reranker
+ opt-in cross-encoder reranker (Qwen `qwen3-rerank`; `gte-rerank` v1 khai tử 30/5/2026, `CROSS_ENCODER_RERANK`) + full-context
(`outbound/knowledge_base.py`, `RERANK_ENABLED`). **Rerank theo path** (đo: chi phí rerank chỉ ~272ms/
retrieve, latency analyze ~99% là vòng flagship output-bound — KHÔNG nén được ở tầng retrieval): `/analyze`
gọi `for_org(org, rerank=False)` (hybrid RRF, bỏ rerank — giảm tải quota khi đông user, zero quality cost);
`/lookup` giữ rerank (Q&A pháp lý cần xếp hạng chính xác). structure-aware legal chunking + NFC + citation
extraction (`outbound/legal_chunker.py` — chunk theo Điều/Khoản, nhãn gắn vào `Snippet.source` dạng
`file.md#Điều 5`; `_ARTICLE_RE` YÊU CẦU dấu chấm sau số điều "Điều N." để KHÔNG bắt nhầm dẫn-chiếu đầu-dòng
"Điều N của Luật này" làm mốc điều → chống nhãn citation SAI số điều (citation accuracy = giá trị lõi);
Phase 0 hướng mở rộng tra cứu luật VN, xem `docs/internal/legal-search-expansion.md`),
citation closure document-aware đi theo dẫn chiếu kéo về điều luật liên quan ở ĐÚNG văn bản đích
(`CitationClosureRetriever`, `CITATION_CLOSURE`; article-level: `extract_article_refs` phân giải "Điều 9 của
NĐ 123/2020"→đúng file qua map doc_id, "của Luật này"→cùng file; doc-level: cạnh amends/amended_by/replaced_by/
guided_by từ front-matter → kéo VB sửa đổi/thay thế/hướng dẫn liên quan; dựng cạnh bằng rule không LLM — Phase 2), lọc hiệu lực mặc-định-chỉ-trả-văn-bản-còn-hiệu-lực
(`InForceRetriever`, `IN_FORCE_FILTER`, theo front-matter `status`; ý định lịch sử mới hiện bản cũ;
**point-in-time #11**: câu hỏi có mốc thời gian "năm 2020"/"1/6/2022" → trả VB còn hiệu lực TẠI mốc đó
theo effective_date/expiry_date — `_extract_as_of`/`_valid_at`),
căn cứ pháp lý tất định cho từng risk & fallback (`_legal_citation` trong `domain/analysis.py`,
`LEGAL_BASIS_GROUNDING`: tra KB gắn `Risk.legal_basis`/`Fallback.legal_basis` = điều luật còn hiệu lực,
ngưỡng trùng ≥3 thuật ngữ để tránh căn cứ lạc), adaptive routing + chunking (`domain/analysis.py`),
**latency — model right-sizing (3 tầng)**: việc KHÓ (agent phân tích, sinh chiến lược) dùng flagship
`qwen3.7-max`; việc PHỤ yes/no (NLI entailment, verify gộp) dùng `judge` = `qwen-flash` (`QWEN_FAST_MODEL`)
— đo thực tế: NLI flagship ~23s vs flash ~0.5s, flash KHỚP flagship → cắt hậu-agent ~264s→~7s. TRA CỨU
(`lookup`) dùng `qwen-plus` (`QWEN_LOOKUP_MODEL`, ~4-6s vs ~48s flagship, format/citation y hệt) — HYBRID:
câu point-in-time (có năm/ngày, `_PIT_RE`) tự route flagship vì plus yếu hơn ở suy luận thời điểm (đã đo).
**FAST-PATH `/analyze` (`mode="fast"`, `domain/fast_review.py`, `docs/internal/latency-analysis-2026-07.md`)**:
nút thắt latency = agent loop (3–6 call flagship TUẦN TỰ, ~100s). Fast = **1 call** trích rủi ro/fallback
(KHÔNG ReAct) bằng **`fast_review_llm` (cấu hình `QWEN_FAST_REVIEW_MODEL`, mặc định `qwen-flash`)**; populate
ctx QUA `execute_tool` (dùng CHUNG QA + shape với agent) → `_finish_analyze` (post-agent CHUNG deep+fast).
Ít sâu → LUÔN `needs_human_review`. HĐ >`_FAST_MAX`(12000) tự về deep. Route riêng, opt-in (`mode` form
/analyze + chọn "Sâu/Nhanh" web app.html + **Next.js `/app`**) → **accuracy golden (=lookup) KHÔNG đổi; deep
vẫn mặc định**. **LATENCY thật (đo prod warm)**: fast=58s vs deep=129s ban đầu — nút thắt là hậu-agent CHUNG
`_attach_counter_clauses` (soạn counter bằng **flagship** cho illegal/must_fix ~40s). Fix: fast **BỎ auto-counter**
(`fast_auto_counter`/`FAST_AUTO_COUNTER` default OFF; `_finish_analyze(auto_counter=)`) → fast **~15-18s**;
người dùng soạn on-demand qua nút "Đồng ý sửa". Deep KHÔNG đổi (luôn auto-counter). Bật lại counter trong fast:
`FAST_AUTO_COUNTER=1`. **A/B THẬT chọn model (`evaluation/fast_ab.py`, reps=4, nhãn neo luật VN)**: flash=6s
illegal_recall 87.5% + **0 over-flag** (MẶC ĐỊNH — nhanh nhất, accuracy = plus); plus=18s cùng recall nhưng
**25% over-flag** (BỊ ĐÈ, đã bỏ); flagship=72s **0 bỏ sót** (đổi `QWEN_FAST_REVIEW_MODEL=qwen3.7-max` khi ưu
tiên an toàn hơn tốc độ). ĐỘ CHÍNH XÁC fast < deep theo THIẾT KẾ — model nhanh **bỏ sót ~12.5% trái luật** →
bù bằng bắt buộc người duyệt; `_detect_illegal` chỉ NÂNG under-flag (cứu 1 phần hướng bỏ sót nếu grounding tìm
ra điều luật), KHÔNG hạ over-flag. **Cảnh báo RÀ NHANH hiện RÕ mọi kênh** (`_finish_analyze` thêm note `⚡ Bản
RÀ NHANH… có thể BỎ SÓT…` + review_reason; `_review_doc` surface note `_FAST_NOTE_MARK` lên đầu reply Slack/
text; web/Next render notes + human-checkpoint) → người dùng không nhầm fast với deep. **Bài học đã lưu**: n=1
từng khiến tôi chọn plus SAI — phải A/B đủ reps (`fast_ab.py`); model đổi được qua env → đánh giá + thay sau.
Lookup còn: template cố định **Trả lời/Căn cứ**, redact PII câu hỏi trước khi gửi LLM, cache LRU
(`LOOKUP_CACHE_SIZE`, hỏi lặp→0ms), ack "đang tra cứu". **Nhãn ĐỘ TIN CẬY (`domain/confidence.py`
`answer_confidence`)** từ tín hiệu ĐÃ TÍNH (NLI supports + độ tập trung evidence elbow) — Cao/Trung bình/
Thấp-cần-luật-sư, gắn 1 lần idempotent (`append_confidence`), KHÔNG thêm LLM call. Hậu-agent (verify ∥
summary ∥ legal_basis) chạy song song; NLI mỗi clause cũng song song (`_attach_legal_basis`).
eval harness + A/B (`evaluation/`). Hai tầng eval: `run_eval.py` =
fast gate keyword-matching (offline, free, dùng trong CI); `ragas_eval.py` = deep gate RAGAS
LLM-as-judge (Faithfulness / Context Precision / Response Relevancy; + Context Recall + Factual
Correctness khi golden có `reference`), judge = Qwen qua endpoint OpenAI-compatible nên không cần
OpenAI key. Opt-in qua group `eval` (pin langchain <1.0 — RAGAS 0.4.3 cần `langchain_community.chat_models.vertexai`).

Advisory flow (`docs/advisory-flow.md`): `/analyze` nhận vị thế đàm phán (`NegotiationPosition`:
leverage/urgency/relationship/alternatives + **`protected_party`** "bên mình bảo vệ") → agent gán
`Risk.priority` (must_fix/negotiate/acceptable) + **`Risk.legal_status`** {illegal (trái luật, có thể vô
hiệu — kèm `violated_law`) | unfavorable} + sinh `AnalysisResult.strategy` (giữ/nhượng + walk-away/BATNA).
Lawyer-review (Phase A+B+C, `docs/internal/lawyer-review-flow.md`): party-aware + tách TRÁI-LUẬT vs bất-lợi;
prompt rỗng protected_party → mặc định "SME client in {country}". Web gắn nhãn ⚖️ TRÁI LUẬT.
**TẦNG TRÌNH BÀY dùng chung (`domain/presentation.py`, `docs/internal/presentation-research-2026-07.md`)**:
MỘT nguồn ngữ nghĩa `Block`/`Doc` → serialize theo kênh (`to_text` cho Zalo/text, `md_to_slack` cho Slack,
`to_email_wrap` biến-thể-email, `parse_lookup` cấu-trúc-hoá tra cứu). Giải VĨNH VIỄN lớp lỗi trình bày
(markdown `**`↔Slack `*`, giãn dòng, lặp footer) — sửa 1 chỗ, mọi kênh đúng. THUẦN, test offline.

**Reply rà soát — VĂN XUÔI PHÁP LÝ ĐÁNH SỐ (kiểu thư gửi khách; nguồn CHUNG `_review_doc(result)`)**:
`format_chat_reply` (text/Zalo) và `_analysis_blocks` (Slack blocks) đều serialize cùng `_review_doc` →
**câu mở đầu** "Sau khi rà soát <loại HĐ> nhằm bảo vệ <khách>, chúng tôi đề xuất điều chỉnh…" (rỗng →
"không phát hiện…", tránh mâu thuẫn) + **đánh số (1)(2)(3) LIÊN TỤC** gộp rủi ro pháp lý VÀ lỗi soạn thảo/
khác biệt VN–EN. Mỗi rủi ro (`_risk_segments`): "(N) Tại điều khoản '<clause>': <rủi ro>[; trái quy định
tại <điều>… vô hiệu] · Nội dung hiện tại: '<evidence>' · Đề xuất sửa như sau: Tiếng Việt/Tiếng Anh (counter
song ngữ) · Căn cứ". `loại HĐ + TÊN khách bảo vệ` + `drafting_notes` (lỗi soạn thảo + đối chiếu VN–EN) do
`_classify_contract` (1 call judge NHANH, đọc 12000 ký tự để thấy cả 2 bản song ngữ, ISOLATED → accuracy
KHÔNG đổi; `_format_drafting_issue` soạn câu "Tại <vị trí>… đề xuất sửa…", bỏ mục no-op quote==fix, gộp
multiline). Prompt agent CẤM cụm bịa ngoài luật VN ("chế tài chồng lấn"/"bất đối xứng").
**LỖI SOẠN THẢO ĐỒNG NHẤT với rủi ro (thẻ + nút, 15/7)**: `_classify_contract` trả THÊM `drafting_issues`
CÓ CẤU TRÚC (`_drafting_issue_struct` → {location,issue,fix_vi,fix_en}) bên cạnh `drafting_notes` (chuỗi,
compat) → `AnalysisResult.drafting_issues`. Reply render (5)(6)(7) GIỐNG rủi ro (1)-(4): thẻ nhãn-đậm +
nút "Đồng ý sửa" (Slack `_drafting_segments` trả (num,seg,dclause) + `_confirm_drafting_fix` GHI NHẬN
agreed_fix — clause mang trong value nút, KHÔNG cần migration; web app.html `agreeDrafting`; Next.js
`DraftingItem`). Fallback không cấu trúc → chuỗi cũ (không nút). (Trước: drafting là text thường không
nút — user hỏi vì sao (1)-(4) có nút mà (5)-(7) không.) `strategy` lọc câu ONBOARDING/đòi cung cấp HĐ
(`_is_input_request`) — agent đôi khi kết bằng "hãy cung cấp hợp đồng" lọt vào strategy (bug web /app).
**HYBRID auto-counter (`AUTO_COUNTER_ON_ANALYZE` default ON, `_attach_counter_clauses`)**: rủi ro `illegal`/
`must_fix` → tự sinh điều khoản mới INLINE song ngữ (`draft_counter_clause` SONG SONG hậu-agent, bounded
`AUTO_COUNTER_MAX` default 6, ưu tiên illegal; KHÔNG đụng vòng agent → accuracy KHÔNG đổi).
**Nút per-risk "Đồng ý sửa" (nhãn NHẤT QUÁN)**: chưa có counter inline → `_run_amend` soạn cũ→mới song ngữ
vào thread; đã có → `confirm:1` → `_confirm_amend` CHỈ ghi `agreed_fix` (không gọi LLM). **2 NÚT QUYẾT ĐỊNH
cuối reply — Chốt / Sửa lại** (`_review_action_blocks`, gộp feedback+outcome, thay 6 nút cũ): Chốt →
outcome=accepted + feedback=helpful; Sửa lại → rejected + wrong (`_RV_ACTION`; map `_OC_RESULT` giữ cho tin
oc_* CŨ). Web/app.html + Next.js dùng structured DTO (RiskItem 4 phần) + nút Chốt/Sửa lại (`ReviewDecision`).
**BIẾN THỂ GIỌNG (D, `_reformat`)**: trong deal + yêu cầu đổi định dạng ("bản email"/"rút gọn"/"trang trọng
hơn", `_is_reformat_request`) → 'email' = `to_email_wrap` TẤT ĐỊNH (giữ 100% substance, không LLM); giọng
khác = model nhanh viết lại, prompt CẤM đổi số liệu/điều luật/đề xuất, offline→trả nguyên bản.
Công bố AI `_AI_DISCLOSURE_LEGAL` gắn qua `_with_ai_disclosure` (idempotent, 1 lần). Slack: `_md_to_slack`
(`**`→`*`) + cap ≤48 block (Slack chặn 50/tin). **A1 heartbeat** (`on_progress`, `_make_progress_cb`):
analyze cập nhật ack "Đang rà soát… đã phát hiện N rủi ro" (chat.update, throttle ≥8s); web poll 202+progress.
**Phase B — phát hiện TRÁI LUẬT có grounding (`_detect_illegal` trong `domain/analysis.py`, `ILLEGAL_DETECTION`)**:
hậu-agent (sau legal_basis), với mỗi risk `unfavorable` đã có `legal_basis` (điều luật THẬT đã retrieve) →
`nli_contradicts` hỏi judge "điều khoản CÓ trái điều luật này không"; YES rõ → nâng `unfavorable`→`illegal` +
`violated_law` trích từ legal_basis (vd "Điều 466"). BẢO THỦ (nghi ngờ→giữ unfavorable, KHÔNG hạ illegal của
agent), song song mỗi risk, LUÔN ép human-review + note "cần luật sư đối chiếu bản gốc" — định vị là lớp SÀNG
LỌC cho luật sư, không phán quyết. Phụ thuộc `legal_basis_grounding` (cần legal_basis để có điều luật đối
chiếu). KB cần điều luật liên quan (đã thêm Đ.466/468 BLDS — trần lãi vay 20%/năm, lãi quá hạn 150%). Đo thật:
HĐ thương mại phạt 15%→illegal Đ.301; HĐ vay→illegal Đ.466.
**Phase C — Bản ghi nhớ sửa đổi (`domain/amendments.py` `compile_memo` thuần)**: `POST /amendments/compile`
{items} → memo markdown (bảng Điều|Vấn đề|Tính chất|Căn cứ|Đề xuất|Ưu tiên, TRÁI LUẬT sắp đầu) +
`POST /amendments/compile.docx` → tải Word (`outbound/docx_export.py`, group `export`/python-docx; thiếu→501,
markdown vẫn dùng). UI app.html: card "📄 Bản ghi nhớ sửa đổi" gộp risk+fallback → preview + tải .docx.
Đây là lời hứa "fallback theo thế trận thật".
**SỬA-FILE Mức 1 — BẢN ĐỐI CHIẾU redline .docx (`docs/internal/edit-contract-file-research-2026-07.md`)**:
xuất file Word điều khoản CŨ (đỏ + gạch ngang) → MỚI (xanh + highlight) song ngữ + căn cứ, giống "ChatGPT
sửa file" nhưng counter GROUNDED. `domain/amendments.compile_redline` (thuần, TRÁI LUẬT lên đầu, khoá linh
hoạt evidence/old·vi/en·rationale) → `outbound/docx_export.redline_to_docx` (python-docx: `strike`/màu/
highlight) → `POST /amendments/redline.docx`. Isolated → accuracy KHÔNG đổi. UI: nút "📄 Tải bản đối chiếu"
web app.html + Next.js `MemoPanel` (BFF `/api/amendments/redline-docx`). **Slack: nút "📄 Bản đối chiếu"**
(`_review_action_blocks` khi có case_id) → `redline_dl` → `_send_redline` (nền, cô lập org) nạp case →
`_redline_items_from_case` → `redline_to_docx` → **`ChatSenderPort.upload_file`** (SlackSender: flow MỚI
`files.getUploadURLExternal`→PUT bytes→`completeUploadExternal`, cần scope **`files:write`**; Zalo no-op) upload
.docx vào thread; thiếu lib/scope → báo text (web vẫn tải được). Mức 2 (sửa in-place) BỎ; Mức 3 (track-changes)
để hậu-judging.
**FILE WORD CÓ COMMENT (lệnh chat, `docx_export.comment_to_docx`, python-docx ≥1.2 `add_comment`)**: phản ánh
thật user "thêm comment vào tệp này ⇒ trả file có comment như ChatGPT" — nhưng bot RÀ SOÁT LẠI (lỗ hổng định
tuyến). Vá: `_wants_file_export` bắt intent "xuất file/tải bản word/thêm comment vào tệp" → `_handle` trả
`ChatReply(kind="export_doc", ref=case_id)` (KHÔNG re-analyze) → `_process` gọi `_send_comment_doc`: nạp case
(cô lập org) → `_comment_items_from_case` (rủi ro + **lỗi soạn thảo** `case.drafting_issues`) → `comment_to_docx`
(mỗi mục = đoạn trích + 1 bong bóng comment Word: [trạng thái] rủi ro + điều luật vi phạm + đề xuất sửa song
ngữ + căn cứ, TRÁI LUẬT lên đầu) → `upload_file` vào thread. Nhớ case qua `Conversation.last_case_id` (set sau
analyze; cột SQL + migration 0013). `AnalysisCase.drafting_issues` persist (migration 0014) → file comment gồm
CẢ lỗi soạn thảo (không chỉ risks; redline vẫn chỉ risks — drafting không có 'đoạn cũ nguyên văn' để gạch).
KHÔNG lưu toàn văn HĐ (chỉ excerpt/evidence) → file dựng từ dữ liệu case, không phải file gốc.
Verify: integration end-to-end (không LLM) — lệnh chat → upload .docx hợp lệ CÓ comments.xml chứa "Điều 301"
+ đề xuất "8%". KHÔNG thêm nút (user muốn ÍT nút — "chỉ Chốt/Sửa lại"). MCP + observability: `inbound/mcp_server.py` expose tool `analyze_contract` qua Model Context Protocol
(`make mcp`); `outbound/observability.py` `ObservabilityPort` (NoOp / Langfuse qua `LANGFUSE_*`) →
`AnalysisService.observer` emit event mỗi lần analyze.

Chat/memory (`docs/conversation.md`): kênh Zalo/Slack qua `ChatHandler` stateful + `ConversationStorePort`
(in-memory MVP, prod Redis/SQL): nhớ history + deal context; intent routing (tín hiệu HĐ → analyze; **trong
deal + tin là PHẢN HỒI/COUNTER đối tác (`_is_counter_offer`, không phải câu hỏi) → VÒNG ĐÀM PHÁN đa phiên
`negotiate_round` ngay trong thread, nối context các vòng — `_negotiate`/`format_negotiation_reply`**; có deal
context → follow-up qua `reasoner`; câu hỏi pháp lý đứng một mình → `AnalysisService.lookup` tra cứu KB có
grounding, cũng expose qua `POST /ask`). **Định tuyến tinh (`docs/internal/reply-4part-format-plan.md` + fix
Slack 13/7)**: (a) `_is_help_query`/`_is_trust_query` CHỈ khi CHƯA vào deal/thread (đang rà soát/giữa thread
→ "help me…" là HỎI TIẾP, không ra bảng hướng dẫn); `_is_help_query` loại tin có động từ rà soát/tín hiệu HĐ
("help me review this contract" = rà soát); (b) **`in_thread`** (mention giữa thread) → LUÔN follow-up theo
ngữ cảnh, kể cả câu giống tra cứu (không rơi lookup KB chung vứt ngữ cảnh); (c) **yêu cầu rà soát CẢ HĐ
không kèm file** (`_wants_whole_contract_review`, tin ngắn) → dùng **FILE HĐ gần nhất trong thread**
(`_latest_contract_file`: bỏ file bot, ưu tiên tài liệu > ảnh; `fetch_thread` trả kèm `files`) → tải + rà
soát; không có file nào + fresh → **hướng dẫn đính kèm** (HĐ chỉ lưu excerpt, không tự rà lại được).
Webhook: ack nhanh + BackgroundTasks; outbound `chat_senders.py`.
Cảnh báo CHỦ ĐỘNG (autopilot monitor / escalation / impact) đẩy thẳng vào Slack qua sender.
Concurrency/threading: hội thoại định danh theo THREAD (`slack:{channel}:{thread_ts}`) — mỗi thread = 1 deal
riêng, reply LUÔN threaded dưới tin người hỏi (`thread_ts or ts`); **lock per-conversation** (`threading.Lock`
trong `reply_ex`) tuần tự hóa tin cùng hội thoại → chống race load→sửa→save, hội thoại khác chạy song song
(verified test contention; đủ 1 instance, đa-instance cần Redis lock — `docs/internal/scale-concurrency.md`).
**MENTION-GATED + đọc thread (`docs/internal/slack-mention-gating-plan.md`, `SLACK_MENTION_ONLY` default
ON)**: bot Slack CHỈ trả lời khi @mention hoặc DM — không mention = user nói với nhau → IM LẶNG tuyệt đối
(gate cả nhánh edit-rerun; mention người KHÁC không kích hoạt; bot_uid từ `authorizations`). Mention GIỮA
thread → **catch-up**: `sender.fetch_thread` (`conversations.replies`, port `ChatSenderPort.fetch_thread`,
Zalo trả []) đọc các tin bot đã bỏ qua → `_build_thread_context` (THUẦN: redact PII từng tin, bóc mention,
tin bot mình='trợ lý'/bot khác=bỏ, dedup với history, budget 6k giữ tin đầu+đuôi) → ngữ cảnh EPHEMERAL
truyền `reply_ex(thread_msgs=, bot_uid=)` → `_handle(thread_context)` vào _followup/_negotiate (KHÔNG
persist — history vẫn chỉ chứa tin đi qua bot). Mention + **permalink thread** (`_parse_permalink`:
`/archives/<CH>/p<16 số>` → ts chèn chấm trước 6 số cuối; `?thread_ts=` = root) → đọc thread được dẫn
(`thread_required=True`, đọc fail → báo mời bot vào kênh); **V1 chỉ CÙNG kênh** (khác kênh → từ chối,
chống rò rỉ chéo kênh khi bot là member mà người hỏi không); không kèm câu hỏi → mặc định tóm tắt.
**M4 — thread NHIỀU NGƯỜI (`slack-multiuser-context-plan.md`, chốt phương án HIỆN ĐẠI)**: (a) TÊN THẬT
người nói (`resolve_names`/users.info + cache, scope `users:read`, `SLACK_RESOLVE_NAMES` default ON;
thiếu → nhãn ẩn danh 'Người A/B/C' theo thứ tự xuất hiện — tất định); co-mention `<@U…>`→`@tên` (giữ
referent); header 'Người tham gia: … (người hỏi)'; (b) **budget-packing LUÔN-BẬT** 24k ký tự (≈8k token)
— head + tail-4 luôn giữ, phần giữa chọn theo điểm LIÊN QUAN, `_GAP_MARK` chỗ lược, thread ngắn giữ 100%;
(c) **semantic scoring `qwen3-rerank`** (tái dùng rerank_fn KB, wire `ChatHandler(rank_fn=)`) fallback
3 tầng semantic→lexical(stopword VN)→recency (`_relevance_scores`) — tầng lỗi rơi xuống, test offline.
History redact PII trước khi lưu; reply Slack chia nhiều block (`_mrkdwn_blocks`, ≤2900/block, không cụt).
**Persist-first + retry + edit-rerun** (`docs/internal/retry-edit-rerun-research.md`): `reply_ex` lưu tin user
(đã redact) NGAY khi nhận, TRƯỚC `_handle` → lỗi bất ngờ KHÔNG mất tin (dữ liệu audit/flywheel, không hiển thị
lại); chống dup khi turn cuối là user-orphan giống hệt (`_followup` đọc history nên dùng `history[:-1]` bỏ turn
hiện tại — tránh lặp câu hỏi trong prompt). Lỗi xử lý/tải-file Slack → nút **🔁 Thử lại** (`_RetryStore` in-process
TTL 15' + `threading.Lock`, lưu payload NGUYÊN VĂN trong RAM — không phải kho PII thứ hai; **retry_id=uuid RIÊNG
mỗi lỗi** để 2 lỗi cùng thread không đè nhau, payload mang conv_key; button mang retry_id; pop one-shot; interactions
guard sender + respawn `_process` qua BackgroundTasks). Lỗi CỐ ĐỊNH (file quá lớn) KHÔNG nút. **Sửa (edit) CÂU
TRA CỨU → tự chạy lại** đánh dấu 🔄 (`message_changed`, chỉ `_is_legal_lookup` stateless; lọc unfurl/bot/text-
không-đổi; dedup khóa 3-phần `(channel, ts, edited.ts)` qua `_seen_dup` chung có prune); edit tin phân tích/đàm
phán BỎ QUA (tránh merge nego ledger lần 2). Zalo/web không đổi.

Web UI: `web/index.html` (landing, `GET /`) + `web/app.html` (demo UI, `GET /app`): form
upload/dán HĐ + vị thế đàm phán → gọi `/analyze` → bảng risks/fallbacks/strategy/trace +
**human checkpoint** (english_reply bị khóa tới khi reviewer Approve; Reject = chuyển chuyên gia).
+ `web/lookup.html` (`GET /lookup`): form tra cứu luật → `/ask` → câu trả lời dẫn điều/khoản + nguồn + nút feedback
(+ section "VB mới ảnh hưởng HĐ nào?" `/impact`, changelog, redline, **✅ VB còn hiệu lực không?** `checkInForce`:
gọi `GET /in-force/{doc_id}` → verdict CÒN/HẾT hiệu lực (`in_force_status` THUẦN: status + chuỗi replaced_by
+ amended_by; `in_force = _is_in_force(status) AND chưa bị thay thế`) + bản hiện hành nếu bị thay + ghi chú
đã bị sửa đổi. Endpoint đồ-thị `/graph`+`/latest`+`/articles-changed` VẪN CÒN (Next.js frontend + test dùng);
web lookup ĐÃ ĐỔI section lược đồ TVPL → kiểm tra hiệu lực (đơn giản, đúng nhu cầu người dùng). app.html mỗi
fallback có nút "📝 soạn điều khoản phản-đề" (`/counter`). + `web/trust.html` (`GET /trust` + data `GET /trust.json`): **công bố độ tin cậy** (phương pháp đảm bảo +
số đo eval, nguồn chung `domain/trust.py trust_report`/`format_trust_text` — cho cả web lẫn Slack; câu hỏi
"độ chính xác/tin cậy" trên Slack `_is_trust_query` → trả tóm tắt). + `web/dashboard.html` (`GET /dashboard`): system-of-record → `/insights/dashboard`
(HĐ rà soát, phân bố severity, top điều khoản rủi ro, feedback, win-rate chiến thuật).
+ **HƯỚNG DẪN & SỰ CỐ** (`GET /help` render inline HTML; Slack `_is_help_query` "help/trợ giúp/hướng dẫn"
→ trả bảng): nguồn CHUNG `domain/help.py` `format_help_text(channel)`/`help_sections()` (mẫu trust.py) —
4 cách dùng (rà HĐ · tra cứu · đàm phán · độ tin cậy) + 4 gỡ sự cố (lâu chưa trả lời · file không đọc được ·
"chưa đủ căn cứ" · cần người thật); channel đổi mô tả bước nhập. Link "❓ Hướng dẫn" ở nav app.html/lookup.html.

**Frontend Next.js** (`frontend/`, xem `frontend/README.md` — TÁCH KHỎI `web/*.html`, CHƯA deploy; ECS
vẫn chạy `web/*.html`): Next 14 App Router + TS + Tailwind + `next-intl` (SSG song ngữ `/vi` `/en`). Mọi
call API qua **BFF** (`app/api/*` route handler giữ `LG_API_KEY` server-side — KHÔNG lộ browser; helper
`lib/bff.ts`). Trang: `/`·`/app` (analyze async+poll, **format luật sư: dòng đầu loại HĐ+khách hàng bảo vệ,
risk đánh số văn phong pháp lý, nút "Đồng ý sửa"→điều khoản cũ→mới, mục lỗi soạn thảo**, human-checkpoint,
outcome, đàm phán đa phiên, memo+docx, **bản đối chiếu redline .docx**, feedback)·`/lookup` (ask +
**structured: answer/citations/badge tin cậy** + feedback + Autopilot monitor + impact +
**kiểm tra hiệu lực VB** `/in-force` + redline)·
`/dashboard` (client fetch, authed)·`/trust` (SSG/ISR). Component dùng chung ở `components/ui/`
(Card·Section·Badge·Note·PageShell·Button). Quy tắc: không lộ key (BFF), tái dùng ui/, i18n vi/en đối xứng,
authed→`no-store`, `strict:true` không `any`. Ngang tính năng với vanilla; contract verify LIVE.

Upload: `DocumentParserPort` = `OcrFallbackParser(PdfDocxParser, QwenVisionOcr)` — text-PDF/DOCX/TXT
dùng base; scan/ảnh (.png/.jpg/PDF-scan rỗng text) → OCR Qwen-VL (`QWEN_VL_MODEL`), fallback lỗi rõ
khi chưa có key. Còn thiếu (next): escalation chuyên gia thật (hiện chỉ gắn cờ needs_human_review); Zalo
prod cần token/verify OA thật (webhook + sender đã code).

Đàm phán đa phiên (`domain/negotiation.py`, lõi Autopilot Agent): `POST /negotiate` {deal_context,
partner_message, leverage/urgency/…, protected_party, **state**} → `negotiate_round`: nhận bối cảnh deal (từ
/analyze hoặc vòng trước) + **sổ nhượng-bộ** + tin đối tác vừa gửi → `NegotiationRound` {assessment (đối tác
nhượng/giữ gì), strategy (vòng tới), reply_vi/reply_en, status: continue|close|walk_away, **state**,
**walk_away_recommended**}. Reasoner soạn bám vị thế; offline → khung an toàn (grounded=False). `_parse_round`
thuần (ép enum status). **SỔ NHƯỢNG-BỘ CÓ CẤU TRÚC (`NegotiationState`: red_lines/secured/conceded/open_items)**
mang qua các vòng → agent NHỚ chính xác đã nhượng/chốt gì (chống "quên" do context free-text cắt cụt →
nhượng lại thứ đã nhượng / đàm phán lại thứ đối tác đã đồng ý). Mỗi vòng merge delta (`_merge_unique` dedup),
`secured` KHÔNG tụt. **GUARDRAIL walk-away THUẦN** (`should_walk_away(red_line_blocked, has_alternatives)`):
đối tác chặn điểm red-line (must_fix) + ta có BATNA → GHI ĐÈ status→walk_away (bảo vệ vị thế tất định, không
để agent chốt/nhượng tiếp khi điểm sống còn bị chặn); không BATNA → giữ đàm phán. State persist qua
`Conversation.nego_state` (JSON, 3 store, migration 0010); chat seed red_lines = rủi ro must_fix sau /analyze;
`/negotiate` thread state qua request/response (`state_to_json`/`state_from_json` thuần). UI app.html: card
"💬 Đàm phán đa phiên" — dán phản hồi đối tác → round mới, hiện ✅ Đã chốt / ↩️ Ta đã nhượng / 🚨 walk-away,
thread state qua các vòng (`_negoState`), badge status.
**THANG NHƯỢNG-BỘ (concession ladder, `next_moves`)** — CHỦ ĐỘNG không chỉ phản ứng: mỗi vòng agent đề xuất
1-3 nước đi TRAO ĐỔI `{offer, in_return_for, why}` (nhượng điểm rẻ-với-ta ĐỂ ĐỔI LẤY chốt điểm còn mở, hiệu
chỉnh theo leverage; prompt cấm nhượng red-line). **Bảo vệ red-line TẤT ĐỊNH** `screen_moves` (THUẦN): gắn cờ
`near_red_line` cho nước đi đụng điểm sống còn (`_touches`: substring/≥2 token đặc trưng, bỏ stopword VN) —
không tự bỏ, chỉ đánh dấu để người quyết. Hiện ở Slack (🪜) + web (ul, ⚠️ gần red-line). Verify LIVE: LLM
sinh trade thực thụ (nhượng thanh toán 30 ngày ĐỔI LẤY giảm đặt cọc + chốt trọng tài VIAC), không đụng red-line.
**LIVING FLYWHEEL** (`format_tactics_context` thuần): win-rate lịch sử (kết quả đàm phán THẬT của org, từ
`outcomes.win_rates()`) inject vào prompt đàm phán (`negotiate_round(tactics_context=)`) → agent ưu tiên GIỮ
điểm win-rate cao, LINH HOẠT nhượng điểm thấp. Vòng học đóng: usage→Outcome→win_rate→advice đàm phán tốt hơn
(moat system-of-record: chỉ ai LƯU outcome mới có tín hiệu này). Verify: seed 3 outcome → 67% → context đúng.

Counter-clause (`domain/counter_clause.py`): `POST /counter` {clause, risk, suggestion, legal_basis, leverage}
→ điều khoản PHẢN-ĐỀ song ngữ VN/EN dán-được-ngay vào HĐ (khác `english_reply` = câu nhắn đối tác). Qwen
reasoner soạn bám `legal_basis` + vị thế; offline → khung an toàn `grounded=False`, KHÔNG bịa luật.
`_parse_counter` thuần (khối ```json/{} trần, fallback vi=raw). UI: nút "📝 Soạn điều khoản phản-đề" mỗi
fallback trong `web/app.html`.

Moat/flywheel (`docs/moat.md`): `Outcome` (kết quả đàm phán) → `OutcomeRepositoryPort` →
`POST /cases/{id}/outcome`, `GET /insights/tactics`; `AnalysisService` gắn `win_rate` vào fallback
(outcome-aware ranking). Đây là dữ liệu độc quyền — moat thật, không phải tech. **UI đóng vòng**: reply rà
soát (Slack + app.html + Next.js) có 2 nút **Chốt / Sửa lại** → ghi Outcome (mọi điều khoản) + feedback →
nuôi win-rate → lần phân tích sau hiện badge `win X%` (càng dùng càng khôn).

**Sau-ký (post-signature, `docs/internal/next-features-research-2026-07.md`) — ĐÃ CODE, FLAG-OFF (chờ hậu
judging)**: theo dõi nghĩa vụ/hạn chót (`domain/obligations.py`, `OBLIGATION_TRACKING` default False, endpoint
`/obligations*`, migration 0011) · playbook công ty (`domain/policy.py` check vi phạm + gợi ý từ lịch sử,
`ORG_PLAYBOOK` default False, `/org/policy*`, migration 0012) · portfolio nhiều HĐ (`domain/portfolio.py`,
`/portfolio`). Thuần + isolated (repo SQL/InMemory, cô lập org, cascade erasure); UI dashboard.html +
Next.js `PortfolioPlaybook`. Bật qua env khi cần.
**Escalation chuyên gia THẬT** (`POST /escalate` {case_id, reason, via?, channel?}): reviewer Reject (app.html)
→ gửi case cho luật sư qua kênh chuyên gia (`EXPERT_CHANNEL` cấu hình sẵn, hoặc channel truyền vào) — hoàn tất
human-checkpoint (không chỉ gắn cờ mà CHUYỂN tới người thật). Chưa cấu hình kênh → vẫn nhận (ok, sent=False).
System-of-record dashboard: `GET /insights/dashboard` = tổng hợp 1 org (HĐ đã rà soát, rủi ro hay gặp +
phân bố severity, top điều khoản rủi ro, tín hiệu feedback + lỗ hổng KB, top chiến thuật theo win-rate).
`domain/dashboard.build_dashboard` THUẦN (gộp cases/feedback/win_rates). Càng dùng càng nhiều dữ liệu
tích lũy (system-of-record).
Vòng học: `Feedback` (phản hồi người dùng helpful/wrong/incomplete) → `FeedbackRepositoryPort` →
`POST /feedback` (+ nút trên web UI) + `GET /feedback` (export build golden set); gom lỗ hổng KB từ usage thật.
Đóng vòng: `evaluation/feedback_to_golden.py` biến feedback ⚠️ wrong/➖ incomplete → ứng viên golden set
(`expected` rỗng cho luật sư điền) + báo lỗ hổng KB (`gap_report`) → merge vào `legal_golden.json` → eval đo
cải thiện (usage→feedback→golden→đo→vá). Hàm thuần test offline; CLI đọc feedback từ DB qua repo.
Trên Slack: câu tra cứu (lookup) kèm Block Kit buttons 👍/⚠️/➖ (`_feedback_blocks`) → `POST /channels/slack/
interactions` (verify chữ ký trên raw body, replace_original xác nhận). **Reply phân tích: 2 nút Chốt / Sửa
lại** (`_review_action_blocks`/`_RV_ACTION`) → Chốt = accepted+helpful, Sửa lại = rejected+wrong → nuôi CẢ
win-rate (`_record_deal_outcome` mọi điều khoản) LẪN golden-set (feedback), flywheel ngay trên Slack, cô lập
org. **Structured lookup (B)**: `/ask` trả `answer_core`/`citations[]`/`confidence` (parse `parse_lookup` từ
text — KHÔNG đổi generation → accuracy giữ; `answer` FULL vẫn có) → web render link điều luật + badge tin cậy.
Routing: câu có dấu hỏi/từ-để-hỏi (`_is_question`) ưu tiên lookup dù chứa từ khóa HĐ.

"What changed" (`docs`/#10): `GET /changes/{doc_id}` = changelog cấp văn bản (sửa đổi/thay thế bởi/của VB nào,
ngày hiệu lực — suy 2 chiều từ front-matter, `legal_changelog`); `POST /redline` {old,new} = diff text 2 phiên
bản ([+thêm+]/[-bỏ-] + similarity, `domain/redline.py`, difflib tất định, không LLM).

Legal-search (kiểu TVPL — Phase 1, `verified_legal_graphrag_2026_reviewed.md`): **`GET /graph/{doc_id}?depth=`** =
LƯỢC ĐỒ văn bản {nodes (doc_id/title/status/effective_date/in_kb), edges (from/relation/to)} mở rộng đa-hop
(BFS 2 chiều từ front-matter, `legal_graph`); **`GET /latest/{doc_id}`** = map tới VĂN BẢN MỚI NHẤT theo chuỗi
`replaced_by`, chọn bản effective_date lớn nhất khi nhiều (`latest_version`). Ingestion ghi cạnh đồ thị:
`group_relationships`+`to_kb_markdown(relations=)` (front-matter amends/replaced_by/guides…); CON BATCH bulk
`run_bulk` join metadata+content+relationships th1nhng0 (`--bulk`, cần `datasets`; đọc content.parquet THẲNG
bằng pyarrow — `datasets` lỗi cast large_string). HƯỚNG quan hệ đã VERIFY bằng cặp thật (70/2025⇄123/2020):
"được/bị X"=source làm X cho other; "X"=other làm X cho source (`_REL_FIELD`). Engine (closure/in-force/
point-in-time/changelog/impact) ĐÃ có — Phase 1 = nạp graph quy mô lớn + endpoint lược đồ/VB-mới-nhất.
**Phase 2 — article-change ("sửa chỗ nào"/bôi vàng)**: `extract_article_changes` (`legal_chunker.py`, RULE tất
định: "Sửa đổi, bổ sung Điều N"→amend, "Bãi bỏ…Điều N"→repeal, "Bổ sung Điều Na"→add, "Thay thế…"→replace;
lấy động từ GẦN điều nhất, cụm "sửa đổi, bổ sung"=amend) → ingestion TỰ điền `amends_articles` từ thân VB sửa
(thay khai tay). **`GET /articles-changed/{doc_id}`** = đọc luật → ĐIỀU nào đã bị VB nào sửa (`amended_articles`,
'bôi vàng' kiểu TVPL). Đã verify trên data thật (slice hóa đơn: 04/2014→replaced_by→123/2020, lược đồ 12 nodes).

Regulatory change intelligence (chủ động, moat system-of-record): `GET /impact/{doc_id}` = VB pháp luật MỚI
ban hành → case nào của công ty viện dẫn văn bản nó vừa sửa đổi/thay thế/hướng dẫn → cần rà soát lại.
Nối: `affected_doc_files` (suy file luật bị tác động qua changelog quan hệ amends/replaces/guides; trả
{file: {relation, articles}} — `articles` từ front-matter `amends_articles` của VB mới) →
`AnalysisService.regulatory_impact` → `scan_cases` (THUẦN, `domain/regulatory.py`: quét `legal_basis`/`source`
của risk+fallback, khử trùng theo (case,kind,clause,file)). ARTICLE-LEVEL: CHỈ quan hệ `amends` mới lọc theo
`amends_articles` (chỉ cảnh báo case viện dẫn ĐÚNG điều bị sửa, giảm báo động giả); `replaces`/`guides` =
doc-level (thay cả VB → mọi viện dẫn lỗi thời). Cô lập `org_id`.
UI: section "Văn bản mới ảnh hưởng hợp đồng nào?" trong `web/lookup.html`.
Cảnh báo CHỦ ĐỘNG: `POST /impact/{doc_id}/notify` {via: slack|zalo, channel} → quét + `format_impact_alert`
(gom theo case, text) → gửi qua sender tương ứng (truyền vào `build_api(senders=...)` từ container, dùng chung
sender với webhook). Hợp với cron/ops khi VB mới ban hành.
**AUTOPILOT giám sát chủ động** (`POST /monitor/run` {since, via?, channel?}): agent TỰ phát hiện luật MỚI
(`recent_laws`: effective_date >= since) → `AnalysisService.monitor` quét MỌI VB mới × case của org →
digest `format_monitor_digest` → gửi Slack/Zalo nếu có via+channel. KHÔNG cần chỉ từng doc_id (khác /impact).
UI: section "🤖 Autopilot — quét luật mới" trong `web/lookup.html`. Production = cron trên ECS gọi hằng ngày
(`curl -XPOST .../monitor/run -d '{"since":"<hôm-qua>","via":"slack","channel":"..."}'`) → "agent làm việc
khi bạn ngủ" (đúng tinh thần Autopilot Agent). Cô lập org_id.

Security (`docs/security.md`): API-key auth + per-company scoping (`API_KEYS="key:org:VN"`), PII
redaction (`domain/redaction.py`), prompt-injection hardening, upload limit, **right-to-erasure CASCADE**
(`delete_case` xóa case + outcomes (`delete_by_case`) + feedback (`delete_by_ref`) — không để orphan dữ liệu
cá nhân, đúng PDPD/GDPR), rate limiting (`RATE_LIMIT_PER_MIN`), LLM retry/backoff (`adapters/outbound/_http.py`).
CI: `.github/workflows/ci.yml` (ruff + pytest). Qwen via dashscope-intl (Singapore, no-training).
DB: SQLAlchemy 2.0, 1 engine/URL (`pool_pre_ping`+`recycle` an toàn Postgres serverless), org_id index khắp;
migrations Alembic (`migrations/`, head 0009) + `create_all()` cho dev. win_rates SQL GROUP BY; cascade erasure.
**Embed BỀN cho corpus lớn** (`outbound/embedding_store.py` `SqlEmbeddingStore`, `PERSIST_EMBEDDINGS`): lưu
vector vào bảng `kb_vectors` theo sha256(text) → `EmbeddingRetriever(store=)` chỉ embed chunk MỚI, boot KHÔNG
embed lại (giải bài "embed 200 file mỗi boot quá chậm"). embed cũng cắt input ≤6000 ký tự (tránh HTTP 400).
**pgvector ANN** (`PGVECTOR_ANN`, TỰ PHÁT HIỆN): DB Postgres có extension `vector` → thêm cột `vec vector(dim)`
+ tìm EXACT trong Postgres (`ORDER BY vec <=> q`, C/SIMD) thay vì brute-force cosine O(N) trong Python (đo:
Python 98% CPU/truy vấn ở 18k chunk là nút thắt khi mở rộng KB). Đo thật 18k×1024-dim: DB exact KHỚP 100%
brute-force + nhanh 2.9x (582ms vs 1666ms). KHÔNG dùng HNSW (xấp xỉ, mất recall) ở quy mô này — chỉ khi
HÀNG TRIỆU vector. SQLite/không-pgvector → tự fallback brute-force (hành vi cũ, test giữ nguyên). Image DB
compose = `pgvector/pgvector:pg16` (pg16→pg16 giữ data volume; chỉ cần `CREATE EXTENSION`, store tự chạy).
**LƯU Ý: pgvector giải LATENCY/CPU, KHÔNG giải regression accuracy do vocab-collision** — mở rộng KB vẫn
phải selective + eval-gated (`docs/internal/ingest-eval-gated-process.md`).
**Domain-scoped retrieval ĐÃ BẬT MẶC ĐỊNH (9/7, `DOMAIN_SCOPED_RETRIEVAL`, qua gate)**: router tất định
(`outbound/domain_router.py`, đếm keyword theo lĩnh vực, KHÔNG LLM) → top-2 domain của truy vấn → lọc ứng
viên theo `domain:` front-matter (file không nhãn luôn giữ; trong-domain < top_k → fallback base, không bao
giờ tệ hơn). Giải "VB mới vocab-trùng nuốt domain lõi" ở tầng retrieval: ca THẬT phát hiện qua test live —
"phạt vi phạm hợp đồng THƯƠNG MẠI tối đa %?" bị **PDPD Đ.8 (phạt HÀNH CHÍNH 5% doanh thu, 5 khoản)** chiếm
top-k chunk → LLM abstain; domain_scoped route→thuong_mai/dan_su, lọc PDPD → LTM Điều 301 lên rank 1. Gate:
`accuracy_eval` 53→**54/54** (chế tài 14/14), `legal_eval` không regress. Tắt: env `DOMAIN_SCOPED_RETRIEVAL=0`.
Prod TODO: encrypt-at-rest (RDS/KMS), RLS (cô lập org hiện ở tầng app), pgvector ANN khi >chục nghìn chunk.

Docker (Postgres + app): `make up` (build+run+migrate), `make down`, `make logs`, `make psql`,
`make help`. Compose sets `DATABASE_URL` to the postgres service; app runs `alembic upgrade head`
on start. `make test` / `make lint` / `make run` run locally without Docker.

Runs without API keys in **stub mode** (LLM clients return `[..._STUB]` text) so the full flow is
exercisable offline. Set `QWEN_API_KEY` in `.env` for real analysis (Qwen-only).

## What this project is

**Legal Guard** (also referred to as "VietDeal Copilot" in the plan) is an AI agent that acts as an
outsourced legal department for Vietnamese SMEs negotiating international commercial contracts. It analyzes
contracts, flags risky clauses, and proposes flexible fallback negotiation tactics based on each party's
real bargaining position. Built for the Qwen Cloud hackathon (deadline 8 Jul 2026, Autopilot Agent
track). Codebase is Qwen-only.

## Knowledge base & legal data (cập nhật 8/7/2026)

**Nguồn data (2, BỔ TRỢ — đều license OK, repo open-source được):**
- **`th1nhng0/vietnamese-legal-documents`** (vbpl.vn, CC BY 4.0) — NĐ/TT + **status + graph quan hệ**
  (amends/replaced_by) → engine in-force/closure/point-in-time DỰA vào front-matter này. Ingest:
  `ingestion/hf_to_kb.py`. NHƯNG **code lớn + luật 2024/2025 thường content RỖNG** (BLHS, BLLĐ, Đất đai
  2024, ĐT 143/2025, GTGT 48/2024).
- **`undertheseanlp/UTS_VLC`** split `2026` (**MIT**, in-force verified, đối chiếu vbpl.vn) — Bộ luật/Luật
  full-text, bù code lớn th1nhng0 rỗng. Schema id/title/type/content, KHÔNG có status/graph → set
  `status: in_force` + thêm `effective_date` thủ công khi promote.
- ⚠️ **TRÁNH** dataset scrape **thuvienphapluat.vn** (vohuutridung/minhdoan17/crawler): vi phạm ToS TVPL
  (dù text public-domain) + thiếu status/graph (mất bộ lọc luật-chết). Chi tiết: memory `vn-legal-data-sources`.

**Quy tắc NẠP (bắt buộc theo, tránh phạm lại — đã trả giá):**
1. **Check `status` + `replaced_by`** trước khi promote. KHÔNG nạp luật đã bị thay (vd ĐT 61/2020 →
   143/2025; GTGT 13/2008 → 48/2024). KHÔNG ép `status=in_force` (sẽ dẫn luật hết hiệu lực — in-force filter
   là tính năng AN TOÀN chống "inapplicable authority", không phải bug).
2. **Code lớn vocab-trùng NUỐT domain lõi** → nạp CHỌN LỌC. Đã BỎ: BLHS ('phạt/vi phạm' nuốt chế tài),
   GTGT ('hóa đơn/xuất khẩu' nuốt hóa đơn), TNDN (rate ở luật gốc). **Đo regression bằng eval MỖI lần nạp.**
3. Sau mỗi đổi KB: chạy `accuracy_eval` lại → cập nhật `/trust` (đừng để số stale).
4. **Nạp LUẬT SỬA ĐỔI (amendment-graph)** → `to_kb_markdown(relations={'amends':[<doc gốc>]})` TỰ rút
   `amends_articles` từ thân VB sửa + dựng cạnh amends/amended_by 2 chiều → engine closure kéo cả gốc+sửa.
   Gate golden cũ KHÔNG regress trước khi giữ. Verify `amended_by` SẠCH (auto-ingest hay điền NHIỄU — vd
   19/2023 KHÔNG sửa DN, đã bỏ). **Đánh giá IMPACT vs use-case trước khi nạp**: KB-stale KHÔNG luôn = phải
   nạp — nếu VB sửa chỉ đụng thủ tục hành chính (không phải luật nội dung use-case dùng) → "document gap"
   (stale_note front-matter) đúng hơn nạp (tránh vocab-collision + rủi ro OCR). Vd NĐ63 trọng tài (124/2018/
   112/2025/18/2026 chỉ sửa TTHC lập tổ chức trọng tài → CHỦ ĐÍCH chưa nạp, ghi stale_note).

**Hiện trạng**: **13 lĩnh vực grounded** (chế tài·hợp đồng·lãi vay·hóa đơn·trọng tài·lao động·doanh
nghiệp·SHTT·PDPD·hôn nhân-GĐ·đất đai·đầu tư·**xây dựng**). Xây dựng nạp 2/7 từ UTS_VLC (Luật XD 2014
50/2014, 162 điều, eval-gated `--repeat=3` = 54/54 không regression + vá over-reach câu giấy phép XD).
**Đợt vá KB-stale 8/7 (DEV-ONLY, prod đóng băng judging)**: rà front-matter → 3 file stale → ingest luật
SỬA ĐỔI qua amendment-graph, gate 54/54 no-regress: **XD 62/2020** (sửa 50/2014, amends_articles Đ.89/107) ·
**SHTT 131/2025** (sửa 50/2005) · **SHTT 131/2025** (sửa 50/2005). NĐ63
trọng tài (124/2018/112/2025/18/2026) = CHỦ ĐÍCH chưa nạp (chỉ TTHC, ghi stale_note). **VBHN-first (8/7,
`docs/internal/vbhn-plan.md`)**: nguồn KB thế hệ 2 = văn bản HỢP NHẤT chính thức VPQH (congbaocdn.chinhphu.vn
PDF text sạch, KHÔNG OCR). Audit 13 domain → phát hiện **PDPD NĐ 13/2023 = luật CHẾT** (bị 91/2025+NĐ356/2025
thay 1/1/2026) + TTTM/HNGĐ bị 81/2025 sửa (front-matter nguồn MÙ). **ĐÃ NẠP 5/8 DOMAIN VBHN (dev-only, mỗi
domain gate 53-54/54, flaky=FDI-floor)**: DN (67/VBHN, 218 điều, thay 59/2020+76/2025-OCR + DN76 candidates 5/5)
· **PDPD** (Luật 91/2025 + NĐ 356/2025 THAY luật chết NĐ 13/2023→expired; in-force filter "chống luật chết"
verified) · TTTM (60/VBHN, 82 điều) · HNGĐ (121/VBHN, 133 điều) · đất đai (133/VBHN, 260 điều, nối 3 phần
dedup). **doc_id GIỮ luật gốc + `vbhn:` metadata** (cạnh closure không mồ côi); chuẩn hóa Ð→Đ; multi-part
dedup giữ điều dài nhất. DEFER: XD 154 (nguồn congbao thiếu Đ.13-48) + hóa đơn 18/VBHN-BTC (số trùng, khó
index) — không gấp (KB hiện có đủ cho golden). Golden vẫn 54 ca
(`evaluation/accuracy_golden.json`; candidate chờ merge HẬU judging = 5 Xây dựng `golden_candidates_B1.json` +
5 DN 76/2025 `golden_candidates_DN76.json` (đo dev 5/5, chủ sở hữu hưởng lợi) = **+10 → 54→64**),
**accuracy THẬT ~98% (53-54/54)** đo với config closure+rerank (`accuracy_report.json` → `/trust`). Đợt nâng
cấp 1/7/2026 (`docs/internal/qwen-tech-upgrades.md`): baseline thực 87% → **98.1%** nhờ (1) **fix moat-overlay
đè điều luật ở /lookup** — `OverlayRetriever` fuse RRF thay vì prepend + `/lookup` dùng `for_org(overlay=False)`
(tactics `premium_tactics.md` chỉ cho /analyze); (2) **Coverage-Gated Abstention** (`elbow_cutoff` cho cổng
relevance quyết trên cụm evidence tập trung → chống over-abstain point-in-time); (3) fix eval brittleness
(`_vn_num_to_digits` số-chữ Việt) + `_expand_abbrev` mở rộng viết tắt (TNHH→trách nhiệm hữu hạn) cho query
retrieval; (4) **lookup+judge temp 0** (determinism — hết flaky must_say). ⚠️ **Dải ~52-54 do LLM hosted
stochastic** (rerank API + judge + answer không byte-deterministic ngay ở temp 0) — 1 ca borderline dao động,
là NHIỄU ĐO không phải regression. **Đã thử + BỎ**: tuning cổng relevance (whack-a-mole, regress ca khác);
per-snippet judge-filter (50/54); PageIndex tree-nav spike (`docs/internal/pageindex-research-plan.md` §4b:
52/54 vs hybrid 54/54, thua point-in-time — NO-GO cho KB hiện tại, revisit khi corpus lớn). **Vượt trần** cần
reranker tốt hơn (self-host AITeamVN/GPU) hoặc domain-aware/paradigm khác. KB ~21 file (5 domain trên nền VBHN chính thức) →
`PERSIST_EMBEDDINGS=1` bắt buộc; pgvector khi corpus rất lớn.

**TT-SAR** (`TemporalTypedRerankRetriever`, `TT_SAR_RERANK` opt-in OFF): rerank đồ-thị lan truyền điểm theo
cạnh CÓ LOẠI + THỜI GIAN (guides/amends boost, replaced_by suppress+redirect có cổng point-in-time, dual
log-degree penalty — mở rộng SAR `arXiv:2604.06173`). Trung tính accuracy trên golden hiện tại → giữ OFF cho
Qwen; là đóng góp creativity dành cho cuộc thi CockroachDB (`docs/internal/cockroachdb-hackathon-research.md`).

## Architecture — Hexagonal (Ports & Adapters)

Full write-up: **`docs/architecture.md`**. Key rule: dependencies point inward; `legalguard/domain/`
never imports adapters or frameworks.

- **`legalguard/domain/`** — business core. `ports.py` defines the interfaces the domain needs
  (`LLMPort`, `KnowledgeBasePort`, `KnowledgeBaseProvider`, `DocumentParserPort`, `LLMError`).
  `agent.py` is the ReAct tool-calling loop; `analysis.py` is the `AnalysisService` use-case;
  `tools.py` holds tool schemas + dispatch (reason-then-format: `reasoning` là property ĐẦU TIÊN của
  `flag_risk`/`propose_fallback` — model suy luận trước khi điền các trường quyết định severity/priority/
  suggestion; optional, vào trace để audit); `models.py` holds DTOs; `tenants.py` the tenant config.
- **`legalguard/adapters/outbound/`** — implement the ports: `qwen.py` (`LLMPort`),
  `knowledge_base.py` (keyword + embedding retrievers + provider), `document_parser.py`.
- **`legalguard/adapters/inbound/http.py`** — FastAPI driving adapter (HTTP ↔ domain).
- **`legalguard/config/container.py`** — composition root, the ONLY place adapters are wired into
  the domain. Swapping a provider = new adapter + one line here; domain stays untouched.

Tenancy is two axes (`tenants.py`): **Tenant = country/jurisdiction** (selects KB `knowledge_base/<CC>/`)
and **Organization = company** (data isolation by `org_id` + per-company KB overlay at
`knowledge_base/_orgs/<org_id>/` via `OverlayRetriever`). Data isolation is per-COMPANY, not per-country;
`AnalysisService.analyze(contract, org)` and cases are scoped by `org_id`. VAI TRÒ LLM (right-sizing):
Qwen flagship `qwen3.7-max` = reasoner (agent phân tích — việc KHÓ); Qwen `qwen-flash` = `judge` (NLI/verify
yes/no — ~0.5s vs ~23s; CŨNG dùng tóm tắt SME `_summarize`); Qwen `qwen-plus` = `lookup_llm` (tra cứu Q&A —
~4-6s, hybrid: point-in-time→flagship). **QWEN-ONLY** — Gemini (provider thứ 2 cũ) ĐÃ GỠ:
summary chuyển qwen-flash vì đo thấy 1 call Gemini ~12-24s CHIẾM TRỌN post-agent (verify+legal_basis
chỉ ~1.5s) → nghẽn; flash cắt post-agent 24s→2.75s (analyze 118-135s→102s; còn lại là agent loop flagship
output-bound, async-mitigated qua web-poll/Slack-background). Muốn provider thứ 2 → thêm adapter + 1 dòng container.
`judge`/`lookup_llm` mặc định = reasoner nếu không cấu hình (giữ tương thích/stub). Deploy target: Alibaba Cloud ECS.

The **Fallback Matrix** (`docs/internal/legal-guard.md` §6) is the product's core logic: a mapping from a partner-imposed
clause → risk analysis → concrete compromise tactic. This is the differentiator (flexible tactics, not rigid
contract templates), so changes here are product-critical and should be grounded in the legal knowledge base
rather than invented.

## Tech stack

Python ≥3.11 + FastAPI, managed with `uv` (`pyproject.toml` + `uv.lock`). Lint with ruff, test with
pytest (`pythonpath=["."]` so tests import `legalguard.*`). LLM access goes through the `LLMPort`
interface in `legalguard/domain/ports.py`; KB retrieval via `KnowledgeBasePort` — keyword-based now,
swappable to a vector DB by adding an adapter, no domain change.
