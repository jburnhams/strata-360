## The cold open: the race's best moment before the title (19 Oct 2026)

**Goal.** The film opens on a hook: a few seconds of the best moment of the race (a shout at the finish, a crowd cheering you up a climb), with its own sound, then the opening title (`edit/bookends.py`) and the race told in order. This answers overview 12, open question 6 ("intro teasers") with one teaser; flashbacks inside the story stay out.

**Built** (`edit/cold_open.py`, `strata360 coldopen FOLDER`, the final film):
- The choice is made from the analysis that is already there, per second of every clip: cheering, shouting, laughter and crowd in the sound (`audio_events.json`), the candidates stage's energy, the scenery rating, a close view of you, steadiness. The first three count half by their rank among the project's own seconds and half by their level. Words you marked MUST USE add a bonus, later clips score a little higher, NEVER USE words keep a window out, and a window lies in usable footage only (`candidates.json` spans). Clips in the first quarter of the race are skipped while later ones exist (the story starts there anyway).
- A window is 6 s, grown to take whole lines (never cut through something said), at most 10 s. Five candidates are kept, at most two per clip and 30 s apart. The camera move is your face (`selfie_close`) when you are close in view, a pan across the crowd (`pan_reveal`) when it is loud and busy, else a push in.
- `strata360 coldopen FOLDER` writes `<project>/strata360/cold_open/cold_open.json` with the best one chosen and prints the candidates with their reasons. `--pick cold-2` chooses another, `--pick none` turns it off, and `--render` makes a preview of each from the proxies (the bookends' 960x540 preview). Your pick is kept when the candidates are found again, as long as that moment is still among them.
- The final film renders the chosen window from the original footage as a piece of its own, with the film's framing for its technique, its speech as burned-in subtitles and no race overlay. The clip's own sound plays under it (voice and all, NEVER USE words silenced, faded, normalised to the film's loudness target: `audio/mix.clip_sound`). Then it cuts to the opening title and the story, whose sound and subtitles move after both (`audio/mix.lead_in`, `film.srt`). `STRATA_COLD_OPEN=0` leaves it out. The choice is not part of the film's key, so changing it keeps every rendered piece. A finished film records which cold open it was made with, and once the choice changes the Final film panel shows it as stopped, so Continue assembles it again with the new one.

**Done means:** the unit tests in `tests/unit/test_cold_open.py` (the choice on synthetic signals, the files, the command) and the integration tests in `tests/integration/test_render.py` (the final film starts with the cold open's piece and its sound) and `tests/integration/test_mix.py` (the sound's length and fades, the lead before the story) pass. *Still to check by eye and ear:* the chosen moment on Legends.

**Not done yet:**
- The preview (`strata360 film`) and the GUI do not show the cold open; it is in the final film only, like the bookends.
- The 360 film (render/vr.py) has no cold open: the piece is a flat picture.
- The music does not start under the cold open: it plays with its own sound, and the opening title stays silent (as before).
- `timemap.json` counts frames from the start of the story, not from the start of the delivered file (this was already so for the opening title).
- An optional vision-model pick between the candidates' previews, as the bookends have.

Size: S (one day).
