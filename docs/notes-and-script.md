# Notes and the voice-over script (README 17 and 18)

## Notes
- **What:** free text, one note for the whole folder (what the race was, who was there, the story of the day) and one per clip (what happened, names, places, feelings, things to mention or avoid).
- **Where:** `<project>/notes.json` = `{"folder": "...", "clips": {"CAM_..._0004_D": "..."}, "updated": {...}}` (`pipeline/notes.py`). The web app edits them (Notes panel: a clip list on the left with a dot on clips that have a note, a text area on the right, saved as you type); API `GET /api/clips`, `GET /api/notes`, `POST /api/notes {folder, text, clip?}`.

## What the script writer is given (`edit/script.py`)
For a planned film (an ordered list of segments: film time, seconds, clip, candidate, technique) and a target length:
1. the folder note and the race facts (distance, hours);
2. per segment: the clip's note; what the wearer says on camera (translated), so narration never talks over it; the **track facts** for that exact span (`gps/context.py`): local time and daylight, race day, hours in, kilometre and percent of the distance, pace and speed, climbing or descending with the gradient, altitude, heart rate; what the camera sees (`scenes.json`: setting, description, tags, weather, lighting) and how many people are in shot;
3. a **word budget per segment** = seconds x speaking rate (default 145 words per minute, so about 2.4 words per second) x 0.85 (breathing room); segments where the wearer speaks get budget 0;
4. optional style ("dry, British, self-deprecating").

## How it is written and checked
A local instruction-tuned LLM (Qwen2.5-7B-Instruct, 4-bit, mlx-lm, in `.venv-vision`; `models/qwen25-7b-instruct-4bit`) is told to write first-person narration in the runner's voice using only the supplied facts (no invented names, places or numbers), with an arc across the film and no repetition, and to return JSON, one line per segment. The result is checked (`script.check`): over-budget lines, narration over the wearer's speech, missing or unknown segments. One retry sends the exact violations back; anything still too long is cut at the last sentence that fits. The saved script (`<project>/scripts/script-*.json`) has, per segment, the text, its words, the estimated speaking seconds and the budget, the facts it was written from, and the totals.

## Commands
```
./strata360 script FOLDER --length 90 [--wpm 145] [--style "dry and understated"] [--seed 1]
```
plans a film of that length from the candidates (the optimiser), writes the script, prints it segment by segment and saves it. Later in the GUI: edit the text per segment, regenerate one segment or a range, pin a line, change the length (the plan and the script re-fit together), then record (README 17).

## Known limits
- Place names are not available offline (coordinates only): the user's notes supply them.
- The plan used for the first script is the music-free default (120 bpm); with a song the segments follow its beats.
- The in-point inside a candidate is not yet chosen by the optimiser; the script assumes the start of the candidate.
