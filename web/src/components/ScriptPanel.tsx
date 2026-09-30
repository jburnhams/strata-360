import { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../usePoll'
import { PanelSkeleton } from './Skeleton'

const short = (id: string) => id.replace(/^CAM_/, '').replace(/_D$/, '').slice(-9)

// The voice-over script: written by the Claude API from your notes, the words you say, and the race facts for each segment of a planned film of the length you choose.
// The key is stored on the server (never shown again); what is sent is text only: notes, transcript, pace / climb / time of day / place names, and short scene descriptions.
export default function ScriptPanel({ folder, onOpen }: { folder: string; onOpen: (clip: string) => void }) {
  const st = usePoll(() => api.script(folder), 3000, [folder])
  const [key, setKey] = useState('')
  const [err, setErr] = useState<string>()
  const [length, setLength] = useState(90)
  const [style, setStyle] = useState('')
  const [model, setModel] = useState<string>()
  const [prov, setProv] = useState<string>()
  if (!st) return <PanelSkeleton title="Voice-over script" rows={4} />
  const provider = prov ?? st.llm.provider, info = st.providers[provider], models = info?.models ?? st.models, configured = info?.configured ?? st.key_configured, label = provider === 'gemini' ? 'Google Gemini' : 'Claude'
  const save = async () => { try { await api.setKey(key, provider); setKey(''); setErr(undefined) } catch (e) { setErr((e as Error).message) } }
  const go = async () => { setErr(undefined); try { await api.generateScript(folder, { length, style: style || undefined, provider, model: (model && models.includes(model)) ? model : (provider === st.llm.provider ? st.llm.model : info?.default) }) } catch (e) { setErr((e as Error).message) } }
  const d = st.latest
  const input = 'rounded-lg border border-stone-300 bg-stone-50 px-2 py-1.5 text-sm dark:border-stone-700 dark:bg-stone-950'
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <h3 className="mb-2 text-sm font-semibold">Voice-over script</h3>
      {!configured ? (
        <div className="mb-3 rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
          <p className="mb-2">The script is written by {label}. Paste its API key: it is stored on the server in <code>secrets.env</code> (gitignored, readable only by you) and is never shown again.
            Only text is sent: your notes, what you say on camera, and race facts (pace, climb, time of day, places) for each segment. No video, audio or pictures.</p>
          <div className="flex gap-2"><input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={provider === 'gemini' ? 'AIza…' : 'sk-ant-…'} className={`${input} flex-1`} />
            <button disabled={!key} onClick={save} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white disabled:opacity-40">Save key</button></div>
        </div>
      ) : (
        <div className="mb-3 flex flex-wrap items-end gap-3 text-sm">
          <label>Film length (s)<input type="number" min={20} max={600} value={length} onChange={e => setLength(Number(e.target.value))} className={`${input} ml-2 w-20`} /></label>
          <label className="flex-1">Style<input value={style} onChange={e => setStyle(e.target.value)} placeholder="e.g. dry, understated, British" className={`${input} ml-2 w-full max-w-sm`} /></label>
          <label>Writer<select value={provider} onChange={e => { setProv(e.target.value); setModel(undefined) }} className={`${input} ml-2`}>{Object.keys(st.providers).map(p => <option key={p} value={p}>{p === 'gemini' ? 'Gemini' : 'Claude'}</option>)}</select></label>
          <label>Model<select value={(model && models.includes(model)) ? model : (provider === st.llm.provider ? st.llm.model : info?.default)} onChange={e => setModel(e.target.value)} className={`${input} ml-2`}>{models.map(m => <option key={m}>{m}</option>)}</select></label>
          <button disabled={st.running} onClick={go} className="rounded-lg bg-emerald-700 px-4 py-2 text-white disabled:opacity-50">{st.running ? 'Writing…' : d ? 'Write another' : 'Write the script'}</button>
          <button className="text-xs underline" onClick={() => api.setKey('', provider)}>remove key</button>
        </div>
      )}
      {err && <p className="mb-2 text-sm text-red-600">{err}</p>}
      {st.last_exit != null && st.last_exit !== 0 && <pre className="mb-2 max-h-32 overflow-auto rounded bg-stone-50 p-2 text-xs text-red-700 dark:bg-stone-950">{st.log}</pre>}
      {d && (
        <div>
          <div className="mb-2 text-sm"><b>{d.title || 'Untitled'}</b> <span className="text-stone-500">· {d.total_words} words, about {d.total_speak_s} s of speech in {d.target_s} s · {d.model ?? d.provider}</span></div>
          <ul className="divide-y divide-stone-200 text-sm dark:divide-stone-800">
            {d.lines.map(l => (
              <li key={l.seg} className="flex gap-3 py-1.5">
                <span className="w-16 shrink-0 font-mono text-xs text-stone-500">{Math.floor(l.film_start_s / 60)}:{String(Math.floor(l.film_start_s % 60)).padStart(2, '0')}<br />{l.seconds}s</span>
                <button className="w-20 shrink-0 text-left font-mono text-xs text-emerald-700 underline dark:text-emerald-400" onClick={() => onOpen(l.clip)}>{short(l.clip)}</button>
                <span className={l.text ? '' : 'text-stone-400'}>{l.text || (l.budget_words === 0 ? '(you speak here)' : '—')}</span>
                {l.text && <span className={`ml-auto shrink-0 text-xs ${l.words > l.budget_words ? 'text-red-600' : 'text-stone-500'}`}>{l.words}/{l.budget_words}</span>}
              </li>
            ))}
          </ul>
          {d.remaining_problems.length > 0 && <p className="mt-2 text-xs text-amber-700">Still to fix: {d.remaining_problems.map(p => `segment ${p.seg}: ${p.problem}`).join('; ')}</p>}
        </div>
      )}
      {!d && configured && <p className="text-sm text-stone-500">No script yet. It plans a film of that length from your usable moments, then writes narration for each segment.</p>}
    </section>
  )
}
