export default function Loading() {
  return (
    <main className="mx-auto max-w-reading px-6 py-16">
      <div className="h-4 w-24 animate-pulse rounded bg-line" />
      <div className="mt-4 h-9 w-2/3 animate-pulse rounded bg-line" />
      <div className="mt-4 h-4 w-full animate-pulse rounded bg-line" />
      <div className="mt-8 h-28 w-full animate-pulse rounded-md bg-line" />
    </main>
  );
}
