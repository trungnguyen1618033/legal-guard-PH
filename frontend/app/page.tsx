import Link from "next/link";

const features = [
  { t: "Rà soát hợp đồng", d: "Phát hiện điều khoản rủi ro, tách trái luật vs bất lợi, đề xuất chiến thuật theo vị thế của bạn." },
  { t: "Tra cứu pháp luật", d: "Trả lời dẫn đúng Điều/Khoản văn bản còn hiệu lực — không bịa, không dẫn luật đã hết hiệu lực." },
  { t: "Đàm phán đa phiên", d: "Dán phản hồi đối tác → vòng đàm phán mới, nhớ bối cảnh, soạn điều khoản phản-đề song ngữ." },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-reading px-6 py-16">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Trợ lý AI pháp lý · doanh nghiệp Việt Nam</p>
      <h1 className="mt-3 text-5xl font-semibold leading-[1.05] tracking-tight">
        Phòng pháp chế thuê ngoài, vận hành bằng AI.
      </h1>
      <p className="mt-5 max-w-[60ch] text-lg text-muted">
        Legal Guard rà soát hợp đồng quốc tế cho SME Việt — bắt điều khoản bất lợi và{" "}
        <strong className="text-ink">trái luật</strong>, đề xuất cách đàm phán lại theo đúng vị thế.
        Mọi câu trả lời <strong className="text-ink">neo vào điều luật còn hiệu lực</strong>, không bịa.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/trust" className="rounded-md bg-accent px-5 py-2.5 font-medium text-white no-underline hover:bg-accent-d">
          Xem độ tin cậy
        </Link>
        <a href="https://legalguard.duckdns.org/app" className="rounded-md border border-line bg-surface px-5 py-2.5 font-medium text-ink no-underline hover:border-accent-d">
          Dùng thử →
        </a>
      </div>

      <div className="mt-16 grid gap-4 sm:grid-cols-3">
        {features.map((f) => (
          <div key={f.t} className="rounded-md border border-line bg-surface p-5">
            <h3 className="text-lg font-semibold text-accent-d">{f.t}</h3>
            <p className="mt-2 text-sm text-muted">{f.d}</p>
          </div>
        ))}
      </div>

      <p className="mt-16 border-t border-line pt-6 text-sm text-muted">
        12 lĩnh vực pháp luật · độ chính xác nội bộ 98% · neo điều luật còn hiệu lực · công cụ hỗ trợ, không thay tư vấn pháp lý.
      </p>
    </main>
  );
}
