import { useEffect, useState } from 'react'
import { api } from './api'
import FolderBrowser from './components/FolderBrowser'
import Workspace from './components/Workspace'

// On load the last project is reopened automatically (remembered by the server); "change" offers another project or a new one.
export default function App() {
  const [folder, setFolder] = useState<string>()
  const [picking, setPicking] = useState(false)
  const [ready, setReady] = useState(false)
  const choose = async (f: string) => { setFolder(f); setPicking(false); await api.open(f).catch(() => {}) }
  useEffect(() => { api.last().then(r => { if (r.folder) choose(r.folder); else setPicking(true) }).catch(() => setPicking(true)).finally(() => setReady(true)) }, [])
  if (!ready) return null
  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-6">
      <h1 className="text-xl font-semibold">Strata 360</h1>
      {picking || !folder ? (
        <>
          <p className="mb-4 text-sm text-stone-500">Open an existing project or create one: choose the folder with your camera files. Results go in a <code>strata360</code> subfolder next to them.</p>
          <div className="max-w-3xl"><FolderBrowser onChoose={choose} onCancel={folder ? () => setPicking(false) : undefined} /></div>
        </>
      ) : <Workspace folder={folder} onChange={() => setPicking(true)} />}
    </main>
  )
}
