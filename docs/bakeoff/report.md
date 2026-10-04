# Object detection bake-off (4 Oct 2026)

Goal: find what is in a clip and roughly where (a bearing, ideally a box), for many kinds of run, not only the two examples (animals in 0013, a river in 0018). Nothing here is wired into the pipeline; this is a measurement.

## Setup

- **Clips (9, chosen from their `scenes.json` tags to differ):** 0002 village/church/dusk, 0004 town road/aid station, 0006 night trail, 0009 river/bridge/dam, 0013 farm animals, 0014 rural village, 0016 snow + wooden platform, 0018 forest river in fog, 0023 foggy muddy trail. No coastal or big-city clip exists in this project, so those are untested.
- **Frames:** 8 times per clip (evenly spaced, from the proxy), each cut into 6 flat 100-degree views (yaw 0, 60 ... 300 in the proxy's frame): 432 images. A hit's bearing is its view yaw plus the box centre's angle in the view.
- **Detectors** (text-prompted, one fixed list of 50 run-relevant terms: `scripts/terms.py`) and **YOLOE prompt-free** (built-in vocabulary, no list). **VLMs** with one open JSON prompt (animals, vehicles, structures, water, terrain, weather, other; `scripts/vlm_bake.py`).
- All on the Mac GPU (MPS / MLX), one job at a time. Raw outputs are in `results/`.
- **There is no labelled ground truth.** What I know by eye: animals only on 0013 (pigs, chickens, ducks, goats in a pen, left-rear of the runner); a river on 0018 and a river/weir/bridge on 0009; a wooden viewing platform on 0016; a portable toilet and cabin on 0002. Precision was judged by looking at 16 random hits per detector (`results/audit_*.jpg`), so the percentages below are rough (plus or minus 15 points).

## Results: box detectors (432 images, 50 terms)

| Model | Time | Hits | Precision (eyeball) | 0013 animals |
|---|---|---|---|---|
| **OWLv2 base** | 231 s (0.5 s/img) | 2136 (>=0.2) | ~60% (10/16) | **chickens in all 4 animal frames, plus pig, duck, goat** |
| Grounding DINO base | 341 s | 398 (>=0.25) | ~65% (8/13) | one frame only |
| LLMDet base | 342 s | 1406 (>=0.25) | ~35% (5/16) | labels them cow/bird, in all 4 frames |
| YOLOE-26s prompt-free | 47 s | 6375 (>=0.25) | poor | cow/sheep/dog, "partridge" |

- **OWLv2 is the best fit** for "find animals and objects with a box": best recall on the case that matters, decent precision, fastest of the three text-prompted models.
- **Grounding DINO** is as precise but almost silent at the 0.25 cut-off (398 hits); a lower threshold might fix that (untested).
- **LLMDet** was no better than OWLv2 here despite its benchmarks. It relabels things (hedge as "tree stump", site cabin as "truck van", the runner's jacket as "tent", people as "statue").
- **YOLOE prompt-free** is fast but its vocabulary is full of junk for this footage (eucalyptus tree, salt marsh, caribbean, adventure, spark, ground squirrel in snow); filtering it with our candidate vocabulary did not fix that.
- **Common failures in all of them:** tiny boxes (a few pixels), the runner's own face/jacket/finger (the selfie stick is always in the rear view), and thin strips of sky as "power line". Fixable with a minimum box size and masking the wearer from the people stage, not tried.

## Results: VLMs (open JSON prompt, 432 views)

| Model | Time | Unparsed | 0013 animal views (of 48) | River views 0009 / 0018 (of 48) |
|---|---|---|---|---|
| Qwen2.5-VL-3B (current) | 54 min (7.5 s/img) | 32 | 6 (chickens, goats, ducks, pigs) | 40 / 11 |
| Qwen3.5-2B | 28 min (3.9 s/img) | 44 | **0** | 27 / **0** |
| Qwen3.5-9B | 93 min (12.9 s/img) | 79 | 8 (chickens, goats, pig) | 36 / 10 |

- **Qwen3.5-2B is not usable** for this (misses the animals and the river).
- **Qwen3.5-9B is only a little better than the 3B** we already use, at 1.7 times the time and 3 times the memory. Not a clear upgrade on this test.
- **Both found the 0013 animals in the views at yaw 240 and 300**, consistent with the detector bearings (about 225 to 290 degrees). So a bearing within a view is dependable for animals; for rivers the VLM only says "in this view" (yes/no per 100-degree view), no box.
- **Both hallucinate in the dark:** 3B said "horse" twice and 9B "dog" twice on the near-black night clip 0006 (frames are almost black with a headlamp pool). The 3B also said "fox" once on 0014. Any real stage needs a brightness guard before asking a VLM anything.
- **Failures:** 3B sometimes emits only "!!!!" (generation glitch, 32 answers affected, with the repetition penalty on); 9B/2B outputs are verbose and get cut at 220 tokens (the `animals` key comes first so it survives, but `structures` and `other` are lost). A flatter schema (lists of plain strings, not objects) would fix the truncation.
- **Not run:** Qwen3.5 box-grounding prompts ("locate every X") that I planned; so the VLMs here only give "which view", not boxes.

## Vocabulary from the RAM tag list (the "filter with the local LLM" idea)

Source: `ram_tag_list.txt` from [recognize-anything](https://github.com/xinyu1205/recognize-anything) (Apache 2.0): 4,584 tags.

1. **Keep/drop (works, noisy):** per-tag "could a runner see this outdoors" yes/no from the local Qwen2.5-7B, read from its answer probabilities (`scripts/vocab3.py`, 7 min for the whole list). 1,535 tags score at least 0.1 and 1,279 at least 0.5. Real things pass (barn, windmill, lamp post, castle, puddle) and people, actions and ideas fail, but there is junk in the kept set (hamper, rag doll, tapestry, wedding bouquet) and some misses ("house" and "bin" score 0). Several essentials are not in the RAM list at all (gate, bollard, railing, rock, tram, cairn, scaffolding). Batch prompts (many tags per request) were unusable: the 7B looped and repeated.
2. **Categories per environment (did not work):** a yes/no per tag per setting (urban, town, farm, forest trail, mountain/snow, inland water, coast, road, race event, wildlife; `scripts/vocab_cats.py`, 47 min). The scores saturate near 1.0 for hundreds of tags and do not separate settings (wolf, yak, toucan and zebra score as forest-trail things; "race event" applies to almost everything). The per-clip packs built from them (`scripts/packs.py`) were therefore useless (400 to 660 tags per clip over the threshold, then arbitrary order) and I did not use them. The bake-off used one fixed 50-term list instead.
3. **Boxable vs scenery question (unreliable):** it called sheep and sheds "scenery".

`vocabulary_candidates.json` has the 1,535 candidates with their scores. It is unreviewed and is a starting point for a hand-curated list, not a result.

## Recommendation

- **Boxes for objects and animals:** OWLv2 (already downloaded) with a curated term list, minimum box size, wearer masking and a darkness guard. Try a lower Grounding DINO threshold and OWLv2-large before deciding between them.
- **Scenery and "is there water / what is the terrain":** the VLM we have (Qwen2.5-VL-3B) is close to the 9B on this footage; per-view yes/no is more trustworthy than a free JSON field with example words in it.
- **Term lists:** hand-curate a general list of 50 to 100 terms plus a few small environment packs written by us, using the candidate file as a source. The 7B is not good enough to categorise by environment; a stronger model (the Qwen3.5-9B is downloaded) or by hand would be needed.
- **Direction:** works. Bearing = view yaw + box angle in the view, for the proxy's frame; for the pipeline use `views.py`'s body-frame views and `views.stab_fn` for the world frame.

## Not covered / caveats

- Eyeball ground truth only; 9 clips; no coast or big-city footage.
- Thresholds were not tuned; prompts were not iterated beyond what is described.
- Not tried: OWLv2-large, SAM 3, Florence-2, Qwen3-VL, Qwen3.5 grounding prompts, Grounding DINO with a lower threshold, per-term thresholds.

## Housekeeping

- Downloaded into the Hugging Face cache (about 10.5 GB): Grounding DINO base 1.8 GB, LLMDet base 0.9 GB, Qwen3.5-2B 1.6 GB, Qwen3.5-9B 5.6 GB, OWLv2 base 0.6 GB (plus YOLOE-26s-pf, 39 MB, in the scratchpad). 109 GB of disk free afterwards. Nothing was deleted (the shell blocks `rm -rf`).
- Licences to record if any are adopted: RAM list Apache 2.0; OWLv2, Grounding DINO base, LLMDet base reported Apache 2.0 (not individually checked); Qwen3.5 Apache 2.0 per its model card (not checked for the 2B/9B MLX conversions); YOLOE/ultralytics (AGPL, already in use for YOLO11; not checked).
- Everything here is uncommitted (`docs/bakeoff/`).

## Follow-up: Qwen with no term list, and with boxes (4 Oct, after the user's question)

- **Open-ended listing covers far more than a fixed list.** Qwen3.5-9B's free JSON answers across the 432 views contain 341 distinct phrases, of which only 24 match the 50 terms. It named things no list of ours had: wooden platform (0016, which the detectors called bench, bridge or table), archway, playground, hedge, cobblestone path, street light, brick wall.
- **Box output works** (`results/ground_9b.jpg`, `results/ground_9b.json`, 8 views, prompt "detect every distinct object ... except people ... bbox_2d"). Coordinates are normalised 0 to 1000. The boxes land on the right things: the telegraph pole, buildings, the bridge and the lake on 0009, the rapids on 0018 (labelled "body of water"), and the wooden platform on 0016 (correctly named). It is coarse: generic labels for small things ("structure", "vehicle"), overlapping duplicate boxes, it boxes people despite being told to exclude them (easy to drop), and it mislabels snow beside the platform as "body of water". About 13 s per image.
- **Not tested:** the 8 views chosen did not include the animal frames of 0013 (a slip in my file selection), so box accuracy on the chickens is unknown; only the 9B was tried with boxes.
- **Suggested design, not built:** two stages. Qwen lists and roughly boxes what is in each view (open vocabulary, gives the direction for pan and zoom). OWLv2 then re-runs on the phrases Qwen named, to tighten the boxes of discrete things. This removes the fixed term list.

## Follow-up: the six views miss the ground and the sky (4 Oct)

`results/views_explained.jpg` shows how the six views are cut from a proxy frame; `results/nadir_zenith.jpg` shows what is outside them.

- **Coverage (computed on the sphere, 100-degree views):** six level views cover **75%** of all directions: nothing below -60 or above +60 degrees, and only 69% of the -60 to -30 and +30 to +60 bands. Adding one straight-down (nadir) view gives 88%; nadir plus zenith gives 100% with 8 views; a ring of four views tilted down 50 degrees plus the six level ones also gives only 88% (the cap is the pole, not the ring).
- **What is lost** (`nadir_zenith.jpg`): footprints and animal tracks in snow (0016), the whole weir and the bridge rail (0009, only partly seen from the level view), puddles, markings and anything on the path. Straight up is mostly empty sky (a tree and a cable on 0013), so zenith is low value.
- **The ground has a sampling problem too:** things at the runner's feet pass in about a second, so sampling every few seconds misses most of them whatever the views; distant things last much longer.
- **The nadir view is mostly the wearer** (selfie stick and body below the camera) plus the ground. Mask or ignore the wearer there.
- **Suggestion (not built):** six level views plus the nadir for the VLM (7 views, 88%), the zenith only for the box detector or at a low rate, and a higher sampling rate if ground items matter. The pipeline's `views.py` views (body frame) have the same gap.

## Idea for later (from the user, 4 Oct)

Qwen3.5-9B has a video input mode. After the planner has chosen the virtual cameras, it could be given each planned shot (from the preview render) and say what the viewer sees: subject centred or cut off, what is in frame, whether the shot is dull. That would feed back into the director step. Not tried: the 9B takes about 13 s per still here, so video will cost several times that per shot, and its video mode has not been tested on this footage.

## Follow-up: night footage, and a fast box proposer + Qwen labelling (4 Oct)

**Night footage.** Auto gain does not help: the proxy is 8-bit and crushed, so a 16x gain on the night clip made Qwen worse (9 "car with headlights" claims on 48 views, against 3 vehicle and 2 animal claims before). A "this is a night photo, a lit patch or silhouette is not an animal or vehicle" line in the prompt cut it to 1 claim ("kayak"). The user's decision: do not send night footage to Qwen at all. A gate on `exposure.json` does it cleanly: a frame's `sphere.mean_lin` below about 0.02 skips it. Across the 25 Legends clips only 0006 is that dark (median 0.002, 85% of frames under 0.01; ordinary clips sit near 0.25; 0015 at 0.08 and 0025 at 0.15 are dim but not black and were not tested).

**YOLOE prompting** (`results/yoloe_prompts_*.jpg`, 8 views, `scripts/yoloe_prompts.py`; text mode needs the CLIP text encoder, installed outside the venv in the scratchpad):
- prompt-free: 4 to 16 boxes a view, many of them huge overlapping area boxes with junk names ("winter storm", "cloud forest"); not usable as a proposer without a size filter.
- 11 broad words (object, animal, structure...): 0 to 2 boxes a view. Generic words do not work in YOLOE's text mode.
- 27-term and 50-term lists: sparse but mostly right (1 to 6 boxes a view); mislabels (a container as "house", a platform as "bridge"); miss most chickens.
- **Common terms plus person and worn gear as named classes, with the prompt-free boxes left over as "other"** (the user's design): person/backpack/helmet/hat/glove/jacket boxes cover the people (28 found, including a distant hiker), common terms (tree, house, road, fence, bridge...) are labelled without a model call, and only the leftovers go to Qwen.

**Two-stage test** (`results/two.json`, `results/native_pairs.jpg`, `scripts/twostage.py`; same 8 views as above): leftovers kept only if YOLOE confidence >= 0.30, shorter side >= 8 px, area <= 25% of the view (drops the huge area boxes), not inside a named box. Each is cropped with a 1.8x margin (10 to 60 degree field of view) and `views.crop_plan` decides: 12 boxes had enough pixels (cut from the proxy), 7 were small and were re-rendered at lens resolution by the new `views.CropRenderer`, none was tiny. Qwen3.5-9B labelled a crop in about 2.6 s (a whole view takes about 13 s); 19 leftovers plus the 7 re-renders were 26 calls, 69 s for 8 views including YOLOE.
- Labels are specific and plausible: green container, church steeple, yellow sign (an electric-fence tag), brown bird (a chicken), blue no-parking sign, tall metal pole, hedge, weather vane.
- **Re-rendering helps** (`native_pairs.jpg`): visibly sharper crops, and the label became more specific in 3 of the 7 (small bird to brown bird, blue sign to no parking sign, church steeple to weather vane on a 2.7 degree box).
- **Weaknesses:** recall for small animals is poor at the strict cut (one chicken found in the two pen views, which have dozens); the same church or tree is found again in every view and frame (needs de-duplication across views and times); 4 of 5 leftovers on the forest view were "tall tree trunk"; the wooden platform on 0016 was not proposed as a separate object (it was named "bridge" by the text pass and the leftover was "snowy path").

**Code.** `analysis/views.py` gained `crop_plan`, `crop_rays`, `lens_choice` and `CropRenderer` (one lens decoded per crop when it is clear of the seam, no blending; lens frames decoded once per moment and shared by all of its boxes). Unit tests: `tests/unit/test_views_crop.py` (9, fakes only). Nothing calls it from the pipeline yet.

**Skipping dark clips with the sun height (user's point, 4 Oct).** `gps.clock.sun_elevation_deg` and `gps.context.daylight` (day above 6 degrees, golden hour above 0, twilight above -12, night below) give each clip a label from its GPS position and time, with no video decode. Over the 25 Legends clips (elevation from the track at the clip's start, with the median `mean_lin` from `exposure.json` in brackets): night is 0006 (-36 degrees, exposure 0.002), 0025 (-24, 0.154) and 0007 (-15, 0.286); twilight is 0004, 0005, 0008, 0015 (0.082), 0016; the rest are day or golden hour. 0006 and 0025 are the headlamp clips; 0007 is a lit indoor aid station at 05:12, which the sun rule alone would wrongly skip. A rule that fits all three: skip a clip when the sun is below -12 degrees **and** its exposure median is under about 0.2, and skip any single frame whose `mean_lin` is under about 0.02. That is tuned on three clips, so treat the thresholds as a starting point. 0015 (twilight, exposure 0.08, dark forest) is dim but was not caught and was not tested with Qwen.

## Follow-up: dense scan and three ways to keep false positives away from Qwen (4 Oct)

**Animals with YOLOE** (`scripts/animals.py`, `results/pen_compare.jpg`): an animal-only prompt (chicken, duck, goat, pig, sheep, cow, bird, animal) at confidence 0.08 on a 60-degree view of the pen found 12 boxes when the view was cut from the original lens frame and 2 when it came from the proxy (0.15 on the ordinary 100-degree level views found 0 to 2). Qwen labelled the 12 crops chicken, duck x3, goat (the pig), black chicken, white bird, 2 unclear and 1 wrong ("worm"). The pixels matter more than the prompt.

**Dense scan** (`scripts/scan.py`): 26 views of 60 degrees per frame (rings at -90, -55, -20, +15 and +50 degrees of pitch, including straight down), each cut from the original lens frame at 1024 px (about 17 px per degree, against about 10 for the proxy views), YOLOE with named classes (people and worn gear, common scenery, animals) plus prompt-free leftovers, de-duplicated across neighbouring tiles. About 20 s per frame including the three checks below. 223 candidates over 6 frames (0013 x2, 0016, 0009, 0018, 0002); a sample from each group was labelled by Qwen3.5-9B (`results/sheet_*.jpg`, `labels.json`).

| Check | Candidates removed | What it removed |
|---|---|---|
| Wearer cone (`focus.json`: the wearer's direction, height; plus YOLOE person boxes) | 17 | Mostly right (headlamp, hand, shoe, jacket, bottle); also a few real things next to the wearer (railing, puddle). Missed other runners' legs and poles and one blue jacket. |
| Quality grid (`tex` channel, 15-degree cells, lowest quarter) | 5 | Almost nothing: a 15-degree cell is far too coarse for a box of a degree or two. |
| Texture inside the box (mean absolute Laplacian under 4) | 66 | **Harmful**: it removed the real small things: chickens, ducks, a chimney, a weather vane, a street sign, a wooden platform, portable toilets. A smooth object on a plain background looks flat. Do not use. |
| Second YOLOE look at a zoomed render (is the object re-detected near the centre) | 14 | Mostly large scenery boxes (pine trees, cloud, a road), which is right; also a few real small birds and the church, because the zoom did not magnify the small ones enough. Needs the zoom matched to the object size. |

- **What was left** (102 candidates): mostly real (church steeple, goat, electric-fence tag, street light, overhead wires, railings, a no-parking sign, containers, logs); about a quarter was ground or area bits (asphalt, tyre tracks, snow and lichen patches, tree trunks) plus a few body parts (legs, running poles, a jacket).
- **Qwen never said "unclear"** (0 of 79 crops), even for plain ground or a hand. Its answer cannot be the filter; a stop-list on the label (person parts, road, ground, snow, sky, trunk...) after the call, or a better crop selection, has to be.
- **Suggestion (not built):** keep the wearer cone and widen the person classes (legs, poles, hood); drop the grid and local-texture checks; match the zoom of the second YOLOE look to the object size; label an object once, not once per frame (the proxy is world-locked, so a church stays at the same direction and a tile-by-tile scan finds it again every time); and stop-list the labels.

## Idea (user, 4 Oct): sample by movement and change, not on a fixed interval

Measured on 10 clips with existing data only (GPS speed from `track.fit.npz`, the world-locked `luma` and `fine` channels of `quality_grid.npz` at 2 Hz): pick a new frame when the runner has moved 12 m since the last pick, or when the grid differs from the last pick by more than 1.5 times its usual change over 4 s, never waiting more than 12 s (minimum gap 1 s). 115 frames against 165 for a fixed 4 s (about 30% fewer): 0023 32 against 54, 0018 16 against 24, 0002 3 against 7, 0021 13 against 16. Thresholds are first guesses, and whether the adaptive set finds the same objects as dense sampling is not tested. Further ideas, untried: take the sharpest frame in each interval (the `blur` channel), re-scan only the tiles that changed since their last scan, and label static objects once (they stay at the same direction in the world-locked proxy) so Qwen only sees new or moving things.

## Follow-up: one YOLOE model or two, and how long the word list should be (4 Oct)

Same 156 tile images (6 frames x 26 tiles, 60 degrees, from the original lens frames; `scripts/vocab_cmp.py`, `results/vocab_cmp_*.jpg`, `vocab_cmp.json`):

| Set-up | Seconds a tile | Boxes a frame | Animal-word boxes on 0013 at 1.8 s |
|---|---|---|---|
| A: 35 words + prompt-free (current) | 0.21 | 123 | 37 |
| B: text only, 35 + 38 extra words | 0.09 | 59 | 31 |
| C: text only, about 1,100 curated words | 0.16 | 107 | 18 |
| D: prompt-free only | 0.11 | 131 | 15 |

- A longer list gave worse names (yak, ground squirrel, woodpecker, fern, partridge for a pig, chickens and a bush) and fewer animal hits; words from the 1,100 list (abalone, armadillo, anvil) compete with the ones we want. The medium list B named things most cleanly (cow, sheep, chicken, shed, bush) but did not box the electric-fence tag or the paper notice that the prompt-free model finds. Prompt-free alone has junk names and misses the same animals. The second model costs about 0.1 s a tile (3 s a frame), so keep both: the text model names the known things, the prompt-free leftovers go to Qwen.
- YOLOE's names are hints only (the pig is "sheep", a black bird "cow"); Qwen's label is the one to keep.
- Plan: a medium list grown from Qwen's reviewed labels, not from a bigger source list. The 1,100-word RAM-derived list (`vocab_big.json`) is not used.

## Result: adaptive frames, skipping unchanged tiles, remembering objects (4 Oct)

Scripts `scripts/adapt.py`, `adapt_sim.py`, `scanlib.py`; results `results/sim_table.json`, `adapt_objects.json`, `sheet_objects.jpg`. Three clips: 0013 (running, 10 s, farm), 0018 (mostly standing, 93 s, forest and river), 0021 (steady running, 63 s, forest). Text list = the 35 words + 38 extras (B above) with the prompt-free leftovers; wearer cone; all 26 tiles of 60 degrees from the original lens frames; Qwen3.5-9B labels from a zoomed render.

**Frames.** The distance trigger is now 5 m (was 12), at least 1 s and at most 10 s apart, and the trigger frame is swapped for the sharpest frame (`blur` channel) of the 1.5 s before it. Frames chosen against a fixed 5 s: 0013 5 against 3, 0021 35 against 13 (the running clip gets about 2.7 times as many), 0018 27 against 19 (more than fixed although the runner mostly stands: the scene-change trigger fires on fog and moving trees; this needs tuning). The dense reference was one frame every 2 to 2.5 s (5, 37, 25 frames).

**What each idea saved** (candidates that would reach Qwen, "medium" tile policy: a tile is rescanned when its 160 px thumbnail differs from the one at its last scan by a mean of more than 7 grey levels or a 99th percentile of more than 45):

| Clip | Every dense frame, no memory | Adaptive frames + tile skipping | + object memory (Qwen calls) | Tiles scanned | Dense objects found |
|---|---|---|---|---|---|
| 0013 | 120 | 126 | **74** | 93% | 19 of 19 (animals 1 of 1) |
| 0018 | 679 | 408 | **94** | 87% (69% at the loosest setting) | 18 of 18 |
| 0021 | 255 | 341 | **92** | 100% (87% loosest) | 13 of 15 |
| All | 1054 | 875 | **260** | | |

- **Object memory is the big saving** (about 70 to 80% fewer calls on the long clips, 40% on the 10 s clip): static things stay at the same direction in the world-locked proxy, so each is labelled once. The matching is by direction and size only, so near objects shift between frames as the runner moves and get labelled again.
- **Skipping unchanged tiles saved little** (0 to 13%, up to 31% at the loosest setting on the still clip): thumbnails of a mostly still clip still differ (fog, moving branches, video noise), and everything changes while running. Thresholds are untuned.
- **Frame choice moves effort to where the runner is moving** rather than saving much; the saving is in memory.
- **Coverage** (a "stable object" = one the dense run saw at least twice, 2 to 2.5 s apart; found when the adaptive run saw something within about 3 degrees of its position at some time while it was visible): 50 of 52. The metric is lenient and the sample small; the two misses were on the running clip.

**What Qwen made of the 260 new objects** (4.4 s each including the re-render, 19 minutes in all; 197 left after a label stop-list of person parts and ground/area words): 
- 0013 is good: street light, yellow sign (the electric-fence tag), black goat, brown chicken, white duck, portable toilet, church steeple, sign on a fence post, parked cars.
- Forest clips are dominated by tree trunks and bare branches (about 40% of the kept labels) which are scenery, not features.
- Small things on the ground are misnamed: snow patches as "white fungus", "mushroom", "plastic bag" or "white car", a twig as a "caterpillar" or "insect", leaves as "orange mushroom". They are real marks on the ground but not what Qwen says.
- Suggested next steps: treat trees and trunks as scenery in the stop-list; ignore small ground objects (below about 1.5 degrees and below -40 degrees of pitch) unless YOLOE names them as animals; tune the scene-change trigger; test the tile-skip thresholds; a human review of the label list.

## Does YOLOE find big area things: snow and rivers (4 Oct, user question)

`scripts/area_check*.py`, `results/area_check*.json`. 14 frames (snow: 0016, 0012, 0017, and patches on 0018; water: 0018, 0009 lake and weir, 0020 and 0019 streams; controls with neither: 0013 x2, 0002, 0010, 0023, 0014, 0021), 26 tiles each, YOLOE text prompts, no cap on box size. A term "fires" on a tile when its boxes cover at least 10% of it.

- **Snow.** "snow" alone almost never fires. "snowy ground" fired on 18, 18 and 7 tiles of the three snow frames and on 0 to 4 of the controls at confidence 0.25 (a thin margin on 0017, and the small snow patches on 0018 are missed entirely). Other phrasings and a lower threshold gave different and worse separation ("ground covered in snow" fires on 7 tiles of the lake frame and 6 of the foggy field). "frost" fires on every frame (6 to 20 tiles) and is useless. Results change with the set of competing words and the threshold, so this is fragile.
- **Water.** "river", "lake", "weir" and "flowing river" never fire, even on the river and lake frames. "white water rapids" fires on the turbulent frames (0009 8 tiles, 0020 7) and not on controls, but also on the snow frames (5 and 3), and misses the plain river on 0018 and 0019. "stream in a forest" fires on every frame (7 to 21 tiles) and "muddy brown river" fires on dry controls (7 to 9 tiles).
- **Conclusion.** YOLOE text prompts alone are not reliable for snow or rivers on this footage. For clip-level attributes the existing `scenes` stage (the VLM: weather, tags, setting) already says snow (10 of 12 samples on 0012 and 0017) and the VLM found rivers per view. Untried: YOLOE visual prompts (reference boxes cut from our own footage) and a per-view yes/no water question to the VLM.

## How accurate is the `scenes` stage, and what could replace the vision stages (4 Oct)

**Accuracy test** (`scripts/scenes_eval.py`, `results/scenes_eval_*`): the stage's own `log` prompt, 12 front-view images from 12 clips, judged by eye by the assistant against the picture (lenient: several answers accepted for borderline cases; weather, setting, lighting, lens problem, crowd = 60 fields). The old stage's saved answers (Qwen2.5-VL-3B) scored 53 of 60; Qwen3.5-9B on the same prompt and images scored 51 of 60. No gain from the newer, three-times-larger model. Where they differ: the old model misses a hand over the lens, a prism glare and a small group of runners; the 9B catches those but calls ordinary fog "lens fog" on 6 of 12 images and gives 'fog' as a lighting value. Both got snow right wherever it was on the ground (weather or tag). A tiny sample: no rear images, one rater.

**A bug in the saved data.** In all 25 clips' `scenes.json` the 212 rear-view general answers are empty (`ok` false, setting/weather/lighting/tags null); the 212 rear scenery scores exist, and 200 of 212 front answers exist. From reading `analysis/scenes.py`: `reusable()` keeps earlier answers under view numbers 0 (front) and 1 (rear), but the view numbers in the image files are the yaws 0 and 180, so on the re-run that reused the general answers (scenes v3) every rear answer was dropped. Not fixed.

**Where the stage falls short** (for what we want to know): it sees only front and rear, every 5 s; one setting label and 5 tags per image; no direction for anything; no sides, ground or sky; the lens-problem answers are weak on the 3B. The model age is not the main problem.

**Stages that look at pictures now:** `exposure` (brightness, view quality map), `quality` (15 degree grid, 2 Hz), `people` (YOLO11 pose + InsightFace) with `identity`, `face_view` and the head tracker, `scenes` (VLM), `thumb*`, and for photos `objects` (YOLO11, 80 classes) and `photo_detect`. Proposal for one shared "seeing" stage:
1. Gates first: sun height, exposure and the lens-problem answers decide which moments are scanned at all.
2. One frame sampler for everything (distance moved, scene change, sharpest frame) instead of each stage sampling on its own.
3. Per sampled moment a tile scan (60 degree tiles from the original lens frames, YOLOE medium word list + prompt-free), with people and worn gear named so they are never labelled.
4. New objects only (object memory) go to Qwen for a label, with a stop-list; reviewed labels grow the YOLOE word list.
5. Clip-level attributes (weather, setting, lighting, lens problems, snow, water) from a few views at a lower rate, with a fixed checklist prompt, not free JSON.
6. One output file in world-frame directions (objects with first/last seen and size, attributes over time, people boxes), plus a `scenes.json`-shaped view of it so candidates, the scenery camera and the writer's pack keep working while they move over.
Keep as they are: `exposure`, `quality`, and the face stages (`people` embeddings, `identity`, `face_view`, head tracking) which need pose points and face embeddings that a box detector does not give. Replace: `scenes`, the photo `objects` stage.

## Built: shared sampler, scene labels front and rear, wordlists with statistics (4 Oct)

**In the code now** (all unit-tested; `pytest tests/unit` 1196 passed; nothing committed):
- `analysis/sampling.py`: the moment chooser (distance moved from the race track, scene change and sharpness from the quality grid; 5 m, 1 to 10 s apart). The `scenes` stage uses it by default (`scenes_sampling: adaptive`, `fixed` to go back), with the fixed `scenes_every_s` as the fallback; `views.write_stab_views_proxy(times=...)` cuts the views at those times.
- `analysis/scenes.py`, stage version 4, schema 3. **Bug fixed:** the rear general answers were lost when earlier answers were reused (view numbers 1 and 180 did not match; the unit test's fake had the same wrong number, so it passed). Reuse now asks again only for the images that lack an answer, so old files get their rear answers back for about half the cost of a full run. The summary has separate `front` and `rear` blocks (settings, weather, lighting, crowd, lens problems, tags, scores), so the direction of a label comes for free. The writer's pack still reads the front view only. Existing `scenes.json` files are not changed until the stage is run again.
- `analysis/vocab.json` + `vocab.py` + `vocab_llm.py` + `vocab_stats_seed.json`: categories (race_event, aid_station, forest_trail, snow, moor, water, infrastructure, town_village, urban, farm_rural, wildlife, road_traffic, coast, indoor) with their words (up to 80 for a clip), `always` (people and gear, a core of everyday things, course markers), `retired` words with the reason, and `accepts` (what counts as the same thing). `categorise()` has a local model match a clip's scene labels to the categories (with plain rules added); the per-word numbers (fired, agreed, mislabelled as what, false positive) and per-category numbers (uses, fired, agreed) are kept in a `StatsBook` in the project folder; `canonicalise()` has the model turn odd labels into plain nouns; `review()` has the model decide which frequent new labels become words; `update()` writes the accepted words and the weak-word removals to a project-local list, never to the shared file. `python -m strata360.analysis.vocab categorise|update|report` run it (set `STRATA_VISION_PYTHON` when the vision Python is not at the repo root).

**Measurements behind it**
- **Qwen3.5-4B vs 9B, object labels** (119 YOLOE boxes, `results/crop_labels_4b_vs_9b.jpg`): the 4B took 121 s and the 9B 212 s; the two share a main word on 56%; of 24 sampled disagreements the 9B was clearly better in about 10 and the 4B in 1 (the 4B calls small animals on grass "dog" seven times, signs "building", a wall "roots"). Use the 9B for labels. The old 3B was not tried on crops.
- **Qwen3.5-4B vs 9B, scene labels** (`results/res_exp.json`, 12 front images, 60 fields): 4B 47/47/50 at 384/512/768 px and 51 at 512 sharpened; 9B 49/51/50 and 51; the old 3B scored 53 at 768. Time barely changes with the picture size (9B: 12.8 s at 768, 9.9 s at 384): the cost is writing the roughly 200 tokens of JSON, so a shorter answer is the lever. Qwen preprocessors do not resize our pictures (up to 12.8 and 16.7 million pixels are kept).
- **How far to trust YOLOE's own name** (119 named boxes, labelled by Qwen): the name matched Qwen's label for 33%; by confidence 0.25 to 0.4: 25%, 0.55 to 0.7: 43%, above 0.7: 75% (8 boxes). Dependable classes: car, van, steeple, chimney, fence (100%); not: sheep 12%, snow 17%, animal, waterfall and truck 0%. A confidence cut alone does not make a name safe; the stats book keeps this per word so routing can use a per-word rule.
- **Categories for the 25 clips** (`results/vocab_demo_cats.json`): the model's picks fit the clips (indoor, village plus aid station, forest plus snow, moor for the heath, farm); it adds "wildlife" to almost every forest clip and misses the river on 0018, whose front labels never mention it (the rear labels, now stored, may).
- **Simplifying labels** (136 distinct labels from three clips): the plain rules and the model mostly agree; the model adds value by skipping twigs, leaves, shoes and "small brown object" (40 of 136) and mapping "trail marker" to "marker post". With the fixes, the model's review of the three suggestions the data produced (tree branch, object, leaves) accepted none, correctly.
- **Not yet done:** the length of the word list measured as a curve (35, 75, 150, 400 words); YOLOE and crop quality against input size and sharpening; running the new `scenes` stage on real clips; the object stage itself.

## Standardising on Qwen3.5-9B (4 Oct)

Decision (user): one newer model for every picture-and-text job. The evidence for the choice, from the same pictures:
- **Scene fields** (12 front images, 60 fields; `scripts/scenes_eval*.py`): old Qwen2.5-VL-3B 53; Qwen3.5-4B 47 to 51; Qwen3.5-9B 50 with the first prompt and **55 after fixing how the prompt and the record handle the lens** (the 9B called ordinary fog a fogged lens on half the images, which the candidate builder reads as a blocked lens; the lens option "fog" is gone from the prompt, a lens "fog" in a foggy scene is stored as none, and the record builder is shared with the photo analysis). The 9B takes about 13 s a picture for the general answers, the old 3B about 7.5 s.
- **Object crops** (119 YOLOE boxes; `results/crop_labels_3b_4b_9b.jpg`, `crop_labels_3models.json`): the old 3B says "unclear" for 67 of the 119 (56%) and shares a main word with the 9B on 22%; it also answers "butterfly" for a chicken and "snowflake" for snow. The 4B shares a word with the 9B on 55% but calls 13 of the 41 animal crops "dog" (the 9B none). Time per crop: 3B 1.2 s, 4B 1.0 s, 9B 1.8 s. The 9B is the one to use.
- The 3B also answers some pictures with a row of "!" (the same picture every time; a re-encoded copy works), the 9B did not.

In the code: `scenes_vlm.default_model()` (the `--model` argument, `$STRATA_VLM_MODEL`, `models/qwen35-9b-4bit`, the Hugging Face cache copy of mlx-community/Qwen3.5-9B-4bit, then the old 3B so a machine without the new model still works) is shared by the scene model, the photo analysis (same command) and `vocab_llm`; thinking mode is off for Qwen3.5; an earlier scenes.json made by another model is not reused. Photos already go through the same command and now the same record builder; their `objects` stage still runs the old YOLO11 80-class script and should move onto the new object pipeline when it exists (a photo is one picture: cut it into tiles at its own resolution, detect, label only what the detector cannot name, same word lists and statistics).

## Scenes stage, final settings (4 Oct)

Tested on the 12 judged pictures with the final prompt (`scripts/scenes_final*.py`; 60 fields plus `water` and `ground_snow`, 12 each), Qwen3.5-9B:

| Field of view, size | Fields right | Water | Ground snow | Time a picture |
|---|---|---|---|---|
| 100 degrees, 768 px | 54 | 11 | 12 | 13.3 s |
| 100 degrees, 512 px | 55 | 10 | 12 | 11.3 s |
| 120 degrees, 768 px | 57 | 10 | 12 | 13.6 s |
| **120 degrees, 512 px** | **58** | 10 | 12 | **11.7 s** |
| 130 degrees, 640 px | 58 | 11 | 12 | 12.5 s |

Chosen: **120 degrees, 512 px** (`scenes_fov`, `scenes_px`). Also changed in the prompt: `activity` and `mood` removed (nothing read them), `water` (none, river, stream, lake, sea, waterfall, puddle) and `ground_snow` added, the lens options reworded (no "fog": a foggy scene is not a fogged lens); a lens "fog" in a foggy scene is stored as none. A puddle on a wet road does not count as water when the categories are chosen. The model's name is stored as `mlx-community/Qwen3.5-9B-4bit`, not the cache folder's hash.

Run through the real runner on a scratch project of clip 0013 (ingest, proxy, quality, scenes): 5 adaptive moments, 10 of 10 pictures answered, front and rear blocks, 362 s (the model itself 176 s; the rest was the model files being read from disk right after the heavy proxy render). The caveat: the sample is 12 pictures judged by one person; differences of one or two fields are noise.

Rerun on all 25 clips: 338 moments, 676 pictures, about 3 to 4 hours, run with the resource guard switched off on the user's say-so (3.1 GB of swap left by the earlier model runs was above the guard's 2.6 GB start limit while 81% of memory was free). The 3B results it replaces are kept in the scratch folder only.

## Rerun of the scenes stage on 9 clips against the old 3B files, and the sun field (4 Oct)

First 9 of 25 clips finished (`results/` has none of the project files; the old files were kept in the scratch folder). Rear answers: all present (none before). Moments: 0004 25 to 61, 0005 5 to 11, 0008 11 to 17 (running clips get more), 0002 6 to 3, 0003 9 to 5 (standing ones fewer). Unanswered pictures: none. Lens problems: the 3B reported none anywhere; the 9B flags a few that look real (blocked, glare, droplets on 0004) and no false "fog". Scenery scores about one point lower on every clip (0004 6.4 to 4.8): the 9B rates lower; the candidate builder rescales by project, so anything made from the old scores is out of date. Agreement of the labels with the old file on matched moments: setting 45%, weather 64%, lighting 64%, crowd 71%. Looking at the pictures behind the three biggest changes: weather cloud to clear (23): the new answer is right (clear skies at the race start); setting trail to road (16): new is right (paved road beside a wall); lighting dusk to overcast (18): the old one is right (blue hour just after sunset). Against the sun's height, lighting is consistent in 94% of the old file's moments and 91% of the new one's.

Fix: the sun's elevation is now stored per clip (`sun` stage) and the scene labels use it for dusk (see `docs/progress.md`).
