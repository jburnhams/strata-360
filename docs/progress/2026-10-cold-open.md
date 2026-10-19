# The cold open (19 Oct 2026; `edit/cold_open.py`, `strata360 coldopen FOLDER`)

The film started on the opening title and then told the race in order, so its first seconds were the least eventful part of the day. The cold open puts the race's best moment first, with its own sound, before the title (overview 12, open question 6). The design and what is left are in [plan/cold-open.md](../plan/cold-open.md).

- **Learned:** ranking each signal among the project's own seconds alone flattens it. On a synthetic project a 0.3 cheer that was louder than most seconds ranked 0.88, close to a 0.9 cheer's 0.96, and the position bonus then let it win. Each signal now counts half by its rank and half by its own level (0 to 1), and tied values take the lowest of their ranks, so a level most seconds share (no cheering at all) is not lifted by being common.
- **Learned:** a clip's `audio_events.json` windows are 6 s long every 3 s, so a per-second reading is the mean of the two or three windows over it: a 3 s cheer reads about half its peak at its edges.
- **Tried:** not yet run on Legends. Next: `strata360 coldopen` on Legends with `--render`, look at the five candidates, and render the final film with the chosen one.
