# Unit tests

Fast, hermetic tests of pure logic (synthetic data, fakes). Shared commands, layout, fixtures and file-ownership rules are in [`tests/README.md`](../README.md); read that first. This file is owned by unit-test work: update it freely. Integration notes live in [`tests/integration/README.md`](../integration/README.md).

## Conventions (unit suite, on top of the shared ones in `tests/README.md`)

- Cover the happy path, empty/missing input, malformed input, boundaries, and each error branch (`coverage --cov-report=term-missing` shows what's unreached).
- Property tests (hypothesis) for numeric, parsing and interpolation code where an invariant is easy to state (bounds, monotonic, round-trip, idempotent). Keep them cheap: the `unit` profile (50 examples, no deadline) is loaded in `unit/conftest.py`.
- No ffmpeg, models, or network: anything needing them is an integration test (`tests/integration`).
- Worked examples to copy: `test_server_api.py` (TestClient, fixtures, parametrize), `test_llm_remote.py` (an old script-style file converted: fake HTTP, key files, tiers), `test_track.py` (numeric code with hypothesis and tmp files).

## Coverage ledger (line+branch; update the rows you change)

Numbers from `pytest tests/unit --cov`. `done` = >= 90%. Modules not listed are 0% and `todo`. Dependencies that need models, ffmpeg or a GPU are noted: test their pure parts, and leave the rest to the integration suite.

| Module | Cover | Status / notes |
| --- | --- | --- |
| `server/app.py` | 60% | partial: auth, browse, last, open, notes, log, clips, clock, who done; the rest of the endpoints todo (transcript, script, voiceover, film, final, music, track, edit, state/clear/stop) |
| `edit/upscale.py` | 75% | factor choice, tiling, windows, cache and the night gate with a stand-in network; todo: `load` (needs `spandrel` and weights, run by hand) and `streetview_cam.enlarge`/`render(upscale=True)` (only run by hand on the Legends street view clips) |
| `render/progress.py` | 100% | steps and their times, time by kind of work, the log, the throttled atomic file, a file that cannot be written |
| `render/final.py` (enlarging) | partial | per-shot factor, the renderer size, fitting the enlarged picture, warm-up frames, the key; the render loop itself is covered by `tests/integration/test_render.py` |
| `render/vr.py`, `render/spherical.py` | 84%, 96% | the sphere's direction per shot or per frame, the panel (view, pin, screen), flat-camera transitions as cuts, the settings and the key, footage and proxy windows with a fake renderer and decoder; the spherical boxes on hand-built MP4 trees (moov before and after the media). The real render is in `tests/integration/test_vr_render.py` |
| `render/still.py` | ~90% | frame and piece lookup, the choice and count of auto moments, picture conversion, the file name, the metadata, several times in one worker, the endpoints (start, batch, list, thumbnail; worker faked); the render itself is covered by running it on the footage by hand |
| `gps/track.py` | 52% | partial: `at`, `to_gpx`, cache done; `load_fit`/`load_gpx` need fitdecode/gpxpy (add to requirements-test.txt to test them) |
| `edit/llm_remote.py` | 81% | partial: Vertex/Gemini/Claude request shape, retries and tiers done |
| `edit/remix.py`, `edit/layers.py`, `edit/intensity.py`, `edit/intensity_signals.py`, `edit/music_build.py`, `edit/music_studio.py` | 96-100% | done: synthetic audio and fakes only (clicks, drifting tempo, chord loops, a fake separator); the music-studio endpoints are in `test_music_studio.py` |
| `edit/music_fit.py`, `audio/music_gen/__init__.py` | 98%, 86% | done: the fit and checks on synthetic clicks with the real beat tracker and a fake stretch; the generator with a fake backend and fake file I/O; the build end to end with a fake generator (`test_music_build.py`). `audio/music_gen/acestep_runner.py` and `acestep()`'s subprocess run only against the real model (by hand, progress.md) |
| `edit/stems.py`, the beat tracker, key and bar features in `edit/music.py` | 67% | partial: the cache and separator contract, the tracker and bar features done; `demucs_separator` and the ffmpeg read/write need models and ffmpeg (an integration run on the PC), the rest of `music.py` is the integration owner's |
| `edit/chrono.py`, `transcript_edits.py`, `analysis/follow.py`, `render/parallax.py` | >= 94% | done |
| `analysis/transcript_review.py` and its two endpoints in `server/app.py` | ~100% | done (`test_transcript_review.py`: pace, priority, reviewed marks, the worst-first queue, endpoints) |
| `analysis/candidates.py`, `edit/project.py`, `gps/anchors.py`, `render/seam.py`, `pipeline/clips.py`, `pipeline/config.py`, `pipeline/resources.py` | 81-91% | partial |
| `gps/clock.py`, `gps/context.py`, `gps/overview.py` | 100% | done |
| `overlay/*` | 98-100% | done: fake tile service (`utils/overlay_fakes.py`), synthetic tracks; never the network. `overlay/flyover.py`: camera, style and frames with `mbgl-render` faked (`test_overlay_flyover.py`) |
| `analysis/thumbs.py` | 46% | partial: the overlay thumbnail done; choosing the moment (`quick`, `best`) needs video |
| `analysis/palette.py` | ~95% | done (`test_palette.py`: Lab/LCh round trip, hue choice, harmony swatches, per-pixel contrast choice, grey fallback; the frame reader needs ffmpeg and is not run) |
| `server/mcp_tools.py` | ~95% | done (`test_mcp_tools.py`: each composite tool's digest and limits on canned routes, the tool set read only and small, in-process against the real app, the /mcp mount and its token; the HTTP backend is not run) |
| `server/agent.py` | ~95% | done (`test_agent.py`: the tool loop with a scripted model, pictures, the optional vision description, HTTP errors, the clip-frame route and the chat routes; no network) |
| `server/agent_edit.py` | ~95% | done (`test_agent_edit.py`: argument checks, the approval gate the model cannot grant, forced and throttled backups, the journal, the `edit` tool only in write mode, real edits and approvals through the app) |
| `render/typography.py` | ~95% | done (`test_typography.py`, `test_typography_api.py`: the tagged library, vibes from the project / the script writer / the user, the choice and its pairing rules, element fonts by role, the project file, overrides, samples, the routes and the style actions; specimens are checked for size and content, not looked at) |
| `gps/sun.py` (the `sun` stage), `analysis/scenes.apply_sun` / `patch_sun` | n/a | done: the label boundaries, a clip's start/middle/end sun, clips outside the track, reading the stored field, the clip card taking it, dusk from the sun in the scene labels |
| `analysis/vocab.py`, `vocab.json`, `vocab_stats_seed.json` | n/a | done: the shipped wordlists are checked for consistency; word union and cap, label simplifying, stop/scenery/feature, the stats book (record, merge, round trip, weak words, suggestions), category matching and word review with a fake model, project-local additions and removals |
| `analysis/sampling.py` | n/a | done: the moments chosen by distance moved, scene change and sharpness, the fallbacks, reading the inputs from a clip folder and the track |
| `analysis/objects.py`, `vocab.collect` / `stats_for` | n/a | done: the night, black-frame and wearer gates, candidates from a tile's boxes, de-duplication across tiles, object memory, the whole run with a fake detector, labelling model and lens (routing by the word statistics, audits, stop-list drops, areas, batches), adding up the clips' statistics; `objects_det.py` and `objects_vlm.py` need models (run by hand, see `docs/progress.md`) |
| `analysis/scenes.py` | n/a | done: first run, reuse of front and rear answers, asking again only for missing ones, front and rear summaries, adaptive times |
| `analysis/views.py` (crops) | n/a | `crop_plan`, `crop_rays`, `lens_choice`, `CropRenderer` with fake lenses and frames done (`test_views_crop.py`); the rest of the module needs lens frames |
| `pipeline/ingest.py` | 98% | done |
| `audio/speech.py` | 86% | partial: 101-112 (CLI) todo |
| `audio/wordtimes.py` | 96% | done: pure math and logic covered |
| `audio/dsp.py` | 53% | partial: signal metrics and basic functions done; heavy ffmpeg filters todo |
| `edit/voiceover.py` | 73% | partial: pure math/logic covered; heavy ffmpeg and model downloads skipped/mocked |
| `cli.py` | 0% | todo: pure parsing good candidates |
| `osv/*` | >= 91% | done |
| `pipeline/runner.py` | 84% | done (integration tests for worker concurrency, claim, cache signatures, clear) |
| `pipeline/coverage.py` | 100% | done: stage states, blocked decisions, CLI, API (`unit/test_coverage.py`) |
| `edit/blocks.py` | 99% | done: allocation, dropping, dialogue padding, automatic length, overrides (`unit/test_blocks.py`) |
| `edit/script.py` | 88% | partial: the per-block writer done (`unit/test_script_blocks.py`, scripted model); the beat-window writer and `segment_facts` todo |
| `edit/vo_measure.py` | 93% | done: speech extent, status checks, single and multi-line recordings, `vo.json` reuse (`unit/test_vo_measure.py`, scripted aligner; the real aligner is a manual check) |
| `edit/bookends.py` | 69% | partial: window search, the globe and sequence camera paths, candidates found from a project's face/scene/motion files (kinds, ends of the race, caps, short clips), default title words, `for_film`, the model's answer; rendering, the model run and `title_candidate` need ffmpeg or a model (`unit/test_bookends.py`) |
| `edit/cold_open.py` | 98% | done: the project's own range, windows grown to whole lines, the choice (loudness, early clips, unusable, shaky and NEVER USE footage, MUST USE words, spreading, the camera move), the signals read from clip folders, `run`/`choose`/`for_film`, a kept choice, the `coldopen` command (`unit/test_cold_open.py`); `render_preview` needs proxies |
| `edit/film_text.py` | 61% | partial: reading and checking the text model's options, the vision model's shot rating (frames faked), the score and pick, `for_plan`/`attach`, the preview frames via `fake_run`; the track facts, HUD boxes and the model-driven `options`/`run` are not (`unit/test_film_text.py`) |
| `edit/project.py` | 75% | partial: reading a project from disk, the music switch (built/original), override guards, generated clips in the plan, beat sync fallbacks; `plan_from_script` and the gap planning are integration-sized (`unit/test_project_edit.py`) |
| `edit/hyperlapse.py` | 99% | done: the ramp profile and its integral, landing and the speed cap, the blockers (talk, skipped moments, unusable footage, footage shown elsewhere), the technique switch and its guards, the IMU frame picker on synthetic running, the final and proxy sources, the time map, the sound's fade, the planner end to end with the setting on and off (`unit/test_hyperlapse.py`) |
| `edit/beat_sync.py` | 97% | done: cuts on a drifting track's beats, music start and delay, words and lead-in kept, footage never twice, technique and generated-clip lengths, the film's end, runs of one clip (`unit/test_beat_sync.py`); with a real click track in `integration/test_script_plan_project.py` |
| `edit/line_refit.py` | 93% | done: a longer or shorter take re-fits only its block (windows outside it unchanged, the cut before it kept), footage limits and the warning, a real beat grid and the off-beat report, generated clips re-planned, the saved plan and lines, the timeline's lines and beats (`unit/test_line_refit.py`); the endpoints in `unit/test_server_api.py` |
| `edit/vo_fit.py` | 92% | done: block sizing, speed fallback, music placement, problems (`unit/test_vo_fit.py`); `respeak`/`fit_project` in `integration/test_voiceover.py` |
| everything else | see `--cov-report=term-missing` | todo |

## Known issues in the existing suite

- Several old files assign module globals directly (`R.mem_available_gb = lambda...`, `L.time.sleep = ...`); `restore_globals` papers over a few of them. Convert them to `monkeypatch` when you touch them.
- `test_workers.py` starts real processes and sleeps (about 5 s).
- Integration-side issues (slow `test_edit.py`, the exposure overflow warning) are listed in `tests/integration/README.md`.


### Added by unit work

- `FakeTorchTensor`, `mock_torch`, `FakeHuggingFaceModel`, `mock_transformers` in `tests/utils/fakes.py`: Mock the PyTorch inference graph and transformers dependencies to avoid deep disk loading and processing in the unit suite.
