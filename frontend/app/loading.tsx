export default function Loading() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" role="status" aria-live="polite">
      <div className="flex items-center gap-3 font-mono text-xs text-bunker-muted">
        <span className="status-dot" />
        YÜKLENİYOR…
      </div>
    </div>
  );
}
