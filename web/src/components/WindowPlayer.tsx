import { useEffect, useState } from 'react'
import { api, type ClipDetail } from '../api'
import ClipPlayer from './ClipPlayer'

// One window of one clip in a modal: the clip's own player, limited to the window and started at once.
export default function WindowPlayer({ folder, clip, start, end, title, onClose }: { folder: string; clip: string; start: number; end: number; title: string; onClose: () => void }) {
  const [c, setC] = useState<ClipDetail>()
  useEffect(() => { api.clip(folder, clip).then(setC) }, [folder, clip])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-3xl rounded-xl bg-white p-3 shadow-xl dark:bg-stone-900" onClick={e => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between text-sm"><b>{title}</b><button className="underline" onClick={onClose}>close</button></div>
        {c ? <ClipPlayer folder={folder} clip={clip} thumbKind={c.thumb?.kind} heading={c.heading} focus={c.focus} person={c.person} clarity={c.clarity} scenic={c.scenic} hasPreview={!!c.preview} duration={c.video.source_frames / c.video.nominal_fps} window={{ start, end }} autoStart />
           : <div className="aspect-video animate-pulse rounded bg-stone-200 dark:bg-stone-800" />}
      </div>
    </div>
  )
}
