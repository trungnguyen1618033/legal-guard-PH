// Typed client gọi API Legal Guard (ECS). CHỈ chạy server-side (BFF) — giữ API key kín, không lộ browser.
export const BASE = process.env.LG_API_BASE ?? "https://legalguard.duckdns.org";
const KEY = process.env.LG_API_KEY ?? "";   // nội bộ — chỉ lộ qua authHeaders(), không export

// Header auth dùng chung cho mọi route handler BFF.
export const authHeaders = (extra: Record<string, string> = {}): Record<string, string> =>
  KEY ? { ...extra, "x-api-key": KEY } : extra;

export type TrustMetric = { name: string; value: string; note: string };
export type TrustReport = {
  methodology: { layer: string; desc: string }[];
  metrics: TrustMetric[];
  disclaimer: string;
};

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
    // /trust.json không cần auth + đổi chậm → revalidate 5 phút (ISR).
    next: { revalidate: 300 },
  });
  if (!res.ok) throw new Error(`API ${path} → HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const getTrust = () => apiGet<TrustReport>("/trust.json");

// --- Kết quả phân tích hợp đồng (/analyze → AnalysisResult) ---
export type RiskDTO = {
  clause: string;
  risk: string;
  severity: "low" | "medium" | "high" | string;
  source?: string;
  evidence?: string;
  priority?: string;            // must_fix | negotiate | acceptable
  legal_basis?: string;
  legal_status?: "illegal" | "unfavorable" | string;
  violated_law?: string;
  verified?: boolean;           // agent self-critique (verify_risks): false = chưa xác minh, cần người duyệt
  counter_clause?: { vi: string; en: string; rationale: string; grounded: boolean };  // điều khoản mới INLINE (auto illegal/must_fix)
};
export type FallbackDTO = {
  clause: string;
  suggestion: string;
  english_reply?: string;
  source?: string;
  win_rate?: number | null;
  legal_basis?: string;
};
export type AnalysisResultDTO = {
  tenant: string;
  risks: RiskDTO[];
  fallbacks: FallbackDTO[];
  needs_human_review: boolean;
  review_reasons: string[];
  summary: string;
  trace: Record<string, unknown>[];
  strategy?: string;
  notes?: string[];
  case_id?: string;
  policy_violations?: { policy_id: string; rule_text: string; clause: string; severity: string; kind: string }[];  // vi phạm chính sách công ty (playbook)
  contract_type?: string;       // loại HĐ (do _classify_contract) — dòng đầu văn phong luật sư
  protected_party?: string;     // tên đầy đủ khách hàng được bảo vệ
  drafting_notes?: string[];    // lỗi soạn thảo/chính tả trong HĐ cần sửa
  execution_summary?: {
    total_tool_calls: number; searches: number; risks_flagged: number;
    fallbacks_proposed: number; human_review_requested: number;
  };
};

// GET /in-force/{doc_id} — VB còn hiệu lực pháp luật không (verdict tất định).
export type InForceDTO = {
  doc_id: string;
  title?: string;
  in_force: boolean;
  reason: string;
  effective_date?: string;
  replaced?: boolean;
  latest?: string;
  latest_title?: string;
  amended_by?: { doc_id: string; title?: string }[];
};

// --- Dashboard (system-of-record) — GET /insights/dashboard ---
export type DashboardDTO = {
  cases: { total: number; needs_review: number; total_risks: number; risk_by_severity: Record<string, number> };
  top_risky_clauses: { clause: string; count: number }[];
  feedback: { total: number; by_rating: Record<string, number>; kb_gaps: number };
  top_tactics: { clause: string; win_rate: number; samples: number }[];
};

// --- Sau-ký: portfolio / nghĩa vụ / playbook (A/B/C) ---
export type PortfolioRow = {
  case_id: string; title: string; created_at: string; must_fix: number; illegal: number;
  needs_review: boolean; next_due: string; days_to_due: number | null; urgency: number;
};
export type ObligationDTO = {
  id: string; case_id: string; kind: string; description: string; due_date: string;
  rule: string; party: string; consequence: string; status: string;
};
export type OrgPolicyDTO = { id: string; rule_text: string; kind: string; severity: string; active: boolean };

// Dashboard cần auth + đổi theo org → KHÔNG cache (no-store), render mỗi request trên BFF.
export async function getDashboard(): Promise<DashboardDTO> {
  const res = await fetch(`${BASE}/insights/dashboard`, { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`API /insights/dashboard → HTTP ${res.status}`);
  return res.json() as Promise<DashboardDTO>;
}

export type AskResult = {
  answer: string; sources: string[];
  answer_core?: string; citations?: string[]; confidence?: "high" | "medium" | "low";  // structured (B)
};

// Tra cứu pháp luật: POST /ask (cần auth) — gọi server-side, key kín.
export async function askLegal(question: string, lang: "vi" | "en"): Promise<AskResult> {
  const res = await fetch(`${BASE}/ask`, {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    body: JSON.stringify({ question, lang }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API /ask → HTTP ${res.status}`);
  return res.json() as Promise<AskResult>;
}

// --- Tra cứu nâng cao (lược đồ/tác động/redline) — dùng trong components/LegalTools ---
export type GraphNode = { doc_id: string; title?: string; status?: string; effective_date?: string; in_kb?: boolean };
export type GraphEdge = { from: string; relation: string; to: string };
export type GraphDTO = { nodes: GraphNode[]; edges: GraphEdge[] };

export type LatestDTO = { doc_id: string; title?: string; effective_date?: string; status?: string };

export type ChangelogItem = { relation: string; doc_id: string; effective_date?: string };
export type ChangelogDTO = { doc_id: string; title?: string; status?: string; effective_date?: string; items: ChangelogItem[] };

export type ArticlesChangedDTO = { amended_articles: Record<string, { doc_id: string; effective_date?: string }[]> };

export type ImpactItem = { case_id: string; kind: string; clause: string; relation: string; affected_file: string; affected_article?: string };
export type ImpactDTO = { doc_id: string; impacted_cases: number; case_ids: string[]; items: ImpactItem[] };

export type MonitorAffected = { doc_id: string; title?: string; effective_date?: string; cases: string[] | number };
export type MonitorDTO = { since: string; new_laws_scanned: number; affected: MonitorAffected[]; sent?: boolean };
