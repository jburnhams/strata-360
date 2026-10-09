## 4. Repository layout

```
strata-360/
  README.md  AGENTS.md  NOTICE  requirements.txt  requirements-cv.txt
  docs/                           # overview.md + overview/ (one file per section), progress.md + progress/, implementation-plan.md + plan/, notes-and-script.md, prompts/
  strata360                       # launcher for the CLI (uses .venv, or STRATA_PYTHON)
  scripts/                        # setup_env.sh (build the environment), patch_deepfilternet.py
  src/strata360/
    cli.py  hw.py                 # the CLI (init, run, status, open, serve, film, final, render, who, voiceover ...); per-OS video hardware options
    pipeline/                     # config.py (race.json defaults), clips.py (discovery), ingest.py, stages.py (every stage), runner.py (claims, state, health), retry.py (backoff), resources.py (keeps the machine usable), notes.py, meta.py
    osv/                          # pbdump.py (protobuf reader), calib.py (lens calibration), telemetry.py, meta.py, mp4.py, data/ (IMU offsets)
    render/                       # flat.py (fisheye -> flat view; the shared projection), seam.py (carved seam), parallax.py (optical-flow warp), photo.py (blend, occlusion), camera.py (paths), proxy.py, preview.py, final.py, film.py (composer, transitions)
    analysis/                     # exposure, motion, people / people_detect, identity (who is the wearer), scenes / scenes_vlm, candidates, follow (which person), places, views (aim samples), voices / voices_embed (speakers),
                                  #   sound_events (audio classifier), transcript_edits / transcript_fix / transcribe_gemini / transcribe35 (transcript corrections and the Gemini audio check), thumbs
    audio/                        # dsp.py (analysis, cleaning, mix), speech.py (transcription), wordtimes.py, align.py, background.py (speech-free track, TIGER-DnR), mossformer_cli.py
    edit/                         # chrono.py (the film plan), techniques.py / .json, framing.py + aim.py (where the camera looks), transitions.py, project.py (saved edit), script.py + llm_remote.py (script writer, Gemini keys),
                                  #   voiceover.py (local voice), music.py, optimise.py
    gps/                          # race track (FIT / GPX), clock
    server/                       # app.py (FastAPI), static/ (the built web app)
  web/                            # the app (React + Tailwind + Vite); src/aim.ts mirrors edit/aim.py
  models/                         # downloaded models (gitignored): kokoro, ast, ecapa, insightface, yolo, tiger-dnr (code at a pinned commit + weights)
  tests/                          # unit/ (fast, pure logic), integration/ (ffmpeg, CLI, server; synthetic clip), utils/ (synthetic_osv.py)
  spike/                          # early experiments and studies (asr_eval, encoder_study, proxy_study, ...), tests (test_audio, test_camera, test_render_smoke, test_wordtimes), and thin shims for the moved modules
  races/<race-name>/              # working data per race (gitignored)
    race.json  catalog.json  report.json  report.md  run.log
    clips/<clip-id>/  clip.json  audio.json  transcript.json  alignment.json  exposure.json  [proxy.mp4  proxy.json]  stages.json
```

Working data lives under `races/<race-name>/`. The layout is fixed so every tool can find every artefact. Planned modules not yet written (attention map, proposals, framing solve, assembly, music, handoff, MCP) keep the names in the phase descriptions (section 7).

---
