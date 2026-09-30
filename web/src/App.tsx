import { useState } from 'react'
import { api } from './api'
import FolderBrowser from './components/FolderBrowser'
import Workspace from './components/Workspace'

// Start screen: choose a footage folder (server-side, inside the allowed roots) -> the project is created or continued -> the clip-based workspace.
export default function App() {
  const [folder, setFolder] = useState<string>()
  const choose = async (f: string) => { setFolder(f); await api.open(f).catch(() => {}) }
  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-6">
      <h1 className="text-xl font-semibold">Strata 360</h1>
      {!folder ? (
        <>
          <p className="mb-4 text-sm text-stone-500">Choose the folder with your camera files. Results go in a <code>strata360</code> subfolder next to them.</p>
          <div className="max-w-3xl"><FolderBrowser onChoose={choose} /></div>
        </>
      ) : <Workspace folder={folder} onChange={() => setFolder(undefined)} />}
    </main>
  )
}
