## 2. What we know about the input files

Findings from the sample in `videos/`:

| File | Container | Contents |
|---|---|---|
| `CAM_20260221120007_0019_D.OSV` | MP4 | Two HEVC Main10 streams, each 3840×3840, nominally 50 fps (239 frames in 4.82 s, so a couple of frames were dropped; ffprobe's 49.59 is only the average), one per fisheye lens. AAC stereo audio. Two `djmd` metadata tracks, two `dbgi` debug tracks (see metadata findings below). Attached JPEG thumbnail (688×344). |
| `CAM_20260221120007_0019_D.LRF` | MP4 | Low-res proxy: H.264, 2048×1024 showing the **two fisheye circles side by side (dual-fisheye, not stitched)**, about 24.8 fps, with the same audio and `djmd` tracks. About 5% of the OSV's size. |

Implications:
- **The LRF is NOT stitched** (found in M0, see `progress.md`): it is the same dual-fisheye layout at low resolution. So it cannot be used directly as the equirect analysis proxy. It is still a cheap-to-decode reference: our own stitch of the OSV can be compared to it (by rendering our lens model back to the same layout), and it could be stitched with the same lens model as a fast proxy source. Our pipeline generates its own equirect proxy from the master or from the LRF.
- The OSV needs dual-fisheye to equirectangular conversion to produce a high-quality master. The lens model and calibration are the highest technical risk (§13).
- **Frame timing is not perfectly regular.** The sample is nominally 50 fps but has dropped-frame gaps (frame spacing 20 ms, occasionally 60 ms), so the effective rate averages 49.59. The LRF proxy is nominally 25 fps. All time handling must use each frame's real timestamp (rational), never "frame number / nominal fps", and the clip's `fps` field records the nominal rate plus a dropped-frame count.
- The filename and the container `CreateDate` both say 2026-02-21 12:00:07. The file's modification time is 14:00:13 at +02:00, which is 12:00:13 UTC, about 6 s after the 4.8 s clip started. So `CreateDate` and the filename are **UTC**, not local time (verified on one file only; P0-03 must re-check on more clips). See §6.1.
- **Insta360 `.insv`** also uses two fisheye streams, often one file per lens (`_00_` and `_10_`), and carries gyro data in a proprietary trailer. Exact details must be verified on real files during Phase 1. The pipeline treats it as a second "adapter" behind the same interface.

### 2.1 Metadata findings (decoded from the sample, Osmo 360 model OQ001)

The `djmd` tracks are Protocol Buffers (schema name `dvtm_oq101.proto`, version 2.0.8), one packet every 20 ms (50 Hz), so 239 packets for the 4.8 s clip.

| Track | Content found |
|---|---|
| `djmd` track 1 (about 640 B/packet, 50 Hz) | Per-frame exposure (ISO, shutter, colour temperature, gain), a **unit quaternion orientation** at the frame rate, and further blocks holding **several quaternion samples per packet** (a higher-rate orientation series, likely the gyro-fused attitude at the IMU rate) and a 3-vector that is probably acceleration. This is the stabilisation and horizon-lock source. |
| `djmd` track 2 (about 143 B/packet) | The same per-frame exposure block for the second lens, plus device identity (model `Osmo OQ001`, serial, firmware) and a nominal 50 Hz rate. No motion data. |
| `dbgi` tracks (about 4 KB/packet) | Debug info (`dbginfo_oq101.proto`). Not needed. |
| Container tags | `CreateDate`, encoder `Osmo 360`, original SD-card path, thumbnail, and DJI beauty-filter flags (all zero). |

**No GPS was found** in the tracks. A scan for lat/long-range values and location strings found nothing, and the camera has no built-in GPS. The Osmo 360 can only log position when paired with a phone or GPS remote, and the short clips make that unlikely. **The design therefore assumes no GPS and relies on the camera clock** (§6). GPS decoding is kept as an optional adapter hook in case later footage has it.

**Lens calibration is embedded in the file** (found in M0, see `progress.md`): the first `djmd` packet holds 24 lens-parameter slots (focal length, principal point, five Kannala–Brandt distortion terms, extrinsic quaternion), so stitching does not need a hand-fitted lens model. The sample's colour mode is Normal (D-Log M and HLG are also possible and need a colour pipeline). **Prior art:** [OpenOSV](https://github.com/Kemerd/OpenOSV) (Apache-2.0, C++, Metal on Apple Silicon) already decodes this calibration, stitches with optical-flow seams and multi-band blending, stabilises from the gyro and converts D-Log M to Rec.709/PQ/HLG. Its CLI (`osvtool render --mode equirect`) does not support animated reframing, so the plan is to use it (or our own projection from the same calibration) for the stitch/colour/stabilise stage and do the keyframed reframing ourselves.

**Colour (M0):** decode to 16-bit, blend in linear light with the BT.709 transfer, weight lenses with OpenOSV's FOV-feather-times-occlusion rule (render blend inset 2.6°), and encode BT.709 limited-range Main 10 with correct tags. Normal-mode footage is rendered **as recorded** (DJI's own export adds an undocumented scene-adaptive lift, which is not a reference for absolute brightness). The lens-to-lens exposure match from OpenOSV is implemented but off by default because the seam statistics are unreliable on wet-lens, near-object clips. A bug fixed in M0: the first renders used ffmpeg's default BT.601 RGB-to-YUV matrix with no tags, giving colour errors up to ±36 levels in a player. See `progress.md`.

**Stabilisation and renderer validated (M0):** the per-frame attitude quaternion (`FrameMeta.2.9`, fields read as w,x,y,z) plus two constant matrices reproduces DJI's own stabilised export (correlation 0.993–0.998 on held-out frames; DJI applies exactly the raw attitude, so we can choose our own stabilisation policy). A direct fisheye-to-flat renderer (`spike/render4k.py`, one resample per pixel, no equirect stage) renders 4K at about 10–14 fps on an M4 (roughly 3–5× slower than real time). So the equirect master is **not needed for output**: Phase 7 renders straight from the two lens streams, using the calibration and the telemetry. An equirect proxy is still useful for Phase 2/4 analysis.

**Stitch validated (M0):** a stitch built from the embedded calibration alone reproduces DJI's own export (correlation 0.97–0.98 against a raw DJI 360 export). Confirmed conventions: `d_lens = R(q)·d_body` (not transposed); **video stream 0 is the rear lens and stream 1 the front lens**; refined slots (2, 1); standard equirect layout with the front lens at the centre column. Residual differences are seam parallax near close objects (such as the user's hand on the selfie stick) and a small exposure lift. Details in `progress.md`. DJI's own 360 export applies horizon lock (and a raw, unstabilised export is available with rocksteady off), and its file timestamps are the export time, so timing must always come from the OSV.

Still to do in M0: confirm the quaternion frame convention (axes and handedness), the exact units of the accelerometer block, and whether the proxy `.LRF` carries the same orientation data (it has the same tracks at half the packet count, so probably yes). Insta360 files will need the same investigation.

---
