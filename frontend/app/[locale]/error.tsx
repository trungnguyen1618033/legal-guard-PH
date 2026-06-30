"use client";

// Error boundary cấp locale — bắt lỗi render bất kỳ trang con nào.
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-reading px-6 py-24 text-center">
      <h1 className="text-2xl font-semibold">Đã có lỗi xảy ra / Something went wrong</h1>
      <p className="mt-3 text-muted">
        Không tải được nội dung. Vui lòng thử lại. / Couldn’t load this page. Please try again.
      </p>
      <button
        onClick={reset}
        className="mt-6 rounded-md bg-accent px-5 py-2.5 font-medium text-white hover:bg-accent-d"
      >
        Thử lại / Retry
      </button>
    </main>
  );
}
