// Grey pulsing placeholders shown while data is still loading, so a missing panel never looks like an error or an empty result.
export const Skeleton = ({ className = 'h-4 w-full' }: { className?: string }) => <div className={`animate-pulse rounded bg-stone-200 dark:bg-stone-800 ${className}`} />

export const PanelSkeleton = ({ title, rows = 3 }: { title?: string; rows?: number }) => (
  <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900" aria-busy="true" aria-label={title ? `Loading ${title}` : 'Loading'}>
    {title ? <div className="mb-3 flex items-center gap-2 text-sm font-semibold">{title}<span className="text-xs font-normal text-stone-500">loading…</span></div> : <Skeleton className="mb-3 h-4 w-40" />}
    <div className="space-y-2">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className={`h-4 ${i % 2 ? 'w-2/3' : 'w-full'}`} />)}</div>
  </section>
)
