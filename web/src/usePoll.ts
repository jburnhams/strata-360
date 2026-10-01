import { useEffect, useState } from 'react'

/** Calls `fn` now and then every `ms`; keeps the last good value (a failed poll is ignored). */
export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[]): T | undefined {
  const [value, setValue] = useState<T>()
  useEffect(() => {
    let live = true
    const tick = () => fn().then(v => live && setValue(v)).catch(() => {})
    tick()
    const id = setInterval(tick, ms)
    return () => { live = false; clearInterval(id) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return value
}
