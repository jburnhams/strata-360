import { useState } from 'react'
import { api } from './api'
import FolderBrowser from './components/FolderBrowser'
import ProjectProgress from './components/ProjectProgress'
import NotesPanel from './components/NotesPanel'
import TrackPanel from './components/TrackPanel'

// Start screen: choose a footage folder (server-side, inside the allowed roots) -> the project is created or continued -> progress -> results / export.
export default function App() {
  const [folder, setFolder] = useState<string>()
  const choose = async (f: string) => { setFolder(f); await api.open(f).catch(() => {}) }
  return (
    <main className="mx-auto max-w-3xl px-4 pb-16 pt-6">
      <h1 className="text-xl font-semibold">Strata 360</h1>
      <p className="mb-4 text-sm text-stone-500">Choose the folder with your camera files. Results go in a <code>strata360</code> subfolder next to them.</p>
      {!folder ? <FolderBrowser onChoose={choose} /> : (
        <>
          <div className="flex items-center gap-3 text-sm"><span className="break-all font-mono text-stone-500">{folder}</span><button className="text-emerald-700 underline dark:text-emerald-400" onClick={() => setFolder(undefined)}>change</button></div>
          <ProjectProgress folder={folder} />
          <TrackPanel folder={folder} />
          <h2 className="mt-8 text-lg font-semibold">Notes</h2>
          <NotesPanel folder={folder} />
        </>
      )}
    </main>
  )
}
