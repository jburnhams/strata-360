import { useEffect, useState } from 'react'
import { api, type ClipDetail } from '../api'
import ClipPlayer from './ClipPlayer'
import { Dialog } from 'strata-react'

// One window of one clip in a modal: the clip's own player, limited to the window and started at once.
export default function WindowPlayer({ folder, clip, start, end, title, onClose }: { folder: string; clip: string; start: number; end: number; title: string; onClose: () => void }) {
  const [c, setC] = useState<ClipDetail>()
  useEffect(() => { let live = true; api.clip(folder, clip).then(x => live && setC(x)).catch(() => {}); return () => { live = false } }, [folder, clip])
  return (
    <Dialog title={title} open onOpenChange={o => { if (!o) onClose() }} size="lg">
      {c ? <ClipPlayer folder={folder} clip={clip} thumbKind={c.thumb?.kind} heading={c.heading} focus={c.focus} person={c.person} clarity={c.clarity} scenic={c.scenic} sounds={c.audio_files} hasPreview={!!c.preview} duration={c.video.source_frames / c.video.nominal_fps} window={{ start, end }} autoStart />
           : <div className="aspect-video animate-pulse rounded-control bg-muted" />}
    </Dialog>
  )
}
