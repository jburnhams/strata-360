"""Per-clip exposure / brightness export (`exposure.json`) so an auto-gain step can be added to the final render later.

Every N source frames (default 10 = 5 Hz at 50 fps) it records:
  * the camera's own exposure metadata per lens (ISO, shutter, colour temperature, raw unknown block),
  * scene brightness statistics on a low-resolution, *stabilised* (upright, world-locked) linear-light sphere:
    mean, per-channel mean, luma percentiles (in BT.709 code space), clipped / crushed fractions, sky vs ground means,
  * per-lens means (each lens over its own useful area) for lens-to-lens comparison,
  * a coarse world-frame brightness grid (24 x 12 cells of 15 deg), so the expected brightness of ANY later framing
    can be estimated without decoding the video again.

All times are clip-relative; the definitive UTC comes from clip.json (see README section 5.1). Statistics use the same
BT.709 transfer, lens weights and occlusion mask as the renderer (spike/photo.py).

Usage: python exposure_stats.py CAM.OSV exposure.json [--every 10]
"""
import argparse, json, os, subprocess, sys, time
import numpy as np, cv2
from strata360.osv.calib import read_slots, Lens, quat_to_R, imu_offsets
from strata360.osv.telemetry import read_frames, read_exposure, video_pts
from strata360.render import photo as ph

LENS_PX = 960                # analysis resolution of each lens frame (a quarter of 3840)
SPH_W, SPH_H = 720, 360      # analysis sphere (0.5 deg per pixel)
GRID_W, GRID_H = 24, 12      # world-frame brightness grid (15 deg cells)
SCHEMA_VERSION = 1


def decode_stream(osv, stream, every):
    """Yield (frame_index, uint16 RGB (LENS_PX, LENS_PX, 3)) for every `every`-th decoded frame of one lens stream."""
    cmd = ['ffmpeg', '-v', 'error', '-hwaccel', 'videotoolbox', '-i', osv, '-map', f'0:v:{stream}', '-fps_mode', 'passthrough',
           '-vf', f"select='not(mod(n\\,{every}))',scale={LENS_PX}:{LENS_PX}:flags=area", '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=LENS_PX * LENS_PX * 6 * 4)
    n = LENS_PX * LENS_PX * 6; k = 0
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n: break
        yield k * every, np.frombuffer(buf, np.uint16).reshape(LENS_PX, LENS_PX, 3)
        k += 1
    p.wait()


def luma_lin(rgb):            # BT.709 luma of linear RGB
    return rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)


class Analyser:
    def __init__(self, osv):
        sl = read_slots(osv)
        self.master, self.slave = Lens(sl[2]), Lens(sl[1])       # stream 1 = master (front), stream 0 = slave (rear)
        self.occl_m = ph.occlusion_map(sl[2]['poly_x'], sl[2]['poly_y']); self.occl_s = ph.occlusion_map(sl[1]['poly_x'], sl[1]['poly_y'])
        self.P, self.B = imu_offsets()
        lon = ((np.arange(SPH_W) + 0.5) / SPH_W - 0.5) * 2 * np.pi; lat = (0.5 - (np.arange(SPH_H) + 0.5) / SPH_H) * np.pi
        LON, LAT = np.meshgrid(lon, lat)
        self.dE = np.stack([np.sin(LON) * np.cos(LAT), np.cos(LON) * np.cos(LAT), np.sin(LAT)], -1).reshape(-1, 3)
        self.lat = LAT; self.solid = np.cos(LAT).astype(np.float64)            # solid-angle weight per pixel
        self.rtm = ph.THETA_MAX_DEG - ph.RENDER_INSET_DEG

    def sphere(self, code_m, code_s, quat):
        """Upright (world-locked) linear-light sphere (SPH_H, SPH_W, 3) and its coverage from the two lens frames."""
        M = self.B.T @ quat_to_R(np.asarray(quat)).T @ self.P.T
        d = np.einsum('nj,ij->ni', self.dE, M)                                  # body-frame rays
        sc = LENS_PX / 3840.0
        lin, w = [], []
        for code, L, om in ((code_m, self.master, self.occl_m), (code_s, self.slave, self.occl_s)):
            u, v, th = L.project(d)
            mu = (u * sc).astype(np.float32).reshape(SPH_H, SPH_W); mv = (v * sc).astype(np.float32).reshape(SPH_H, SPH_W)
            samp = cv2.remap(code, mu, mv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            lin.append(ph.EOTF_LUT[samp])
            oc = ph.sample_occl(om, u.reshape(SPH_H, SPH_W), v.reshape(SPH_H, SPH_W))
            w.append(ph.lens_weight(np.degrees(th).reshape(SPH_H, SPH_W), oc, self.rtm, ph.RENDER_FEATHER_DEG))
        th_m = np.degrees(np.arccos(np.clip(d[:, 1], -1, 1))).reshape(SPH_H, SPH_W)   # noqa (kept for debugging)
        ws = w[0] + w[1]; cov = ws > 1e-4
        wn = np.where(cov, w[0] / np.maximum(ws, 1e-9), 0)[..., None]
        return wn * lin[0] + (1 - wn) * lin[1], cov

    def lens_mean(self, code, L, om):
        """Mean linear RGB of one lens over its own useful area (theta < 90 deg, outside the occlusion polygon)."""
        n = LENS_PX; ys, xs = np.mgrid[0:n, 0:n]; sc = 3840.0 / n
        r = np.hypot((xs + 0.5) * sc - L.cx, (ys + 0.5) * sc - L.cy)
        th = np.linspace(0, np.pi, 4000); thd = th * (1 + sum(L.k[i] * th ** (2 * (i + 1)) for i in range(5))); rr = L.fx * thd
        valid = (r < np.interp(np.radians(90.0), th, rr))
        oc = cv2.resize(om, (n, n), interpolation=cv2.INTER_LINEAR) > 0.99
        m = valid & oc
        return ph.EOTF_LUT[code][m].mean(0), float(m.mean())


def stats_for(sph_lin, cov, ana):
    wgt = ana.solid * cov; wsum = wgt.sum()
    rgb = (sph_lin * wgt[..., None]).reshape(-1, 3).sum(0) / wsum
    y = luma_lin(sph_lin)
    ycode = ph.oetf709(y)                                                        # percentiles in display-referred code space
    order = np.argsort(ycode[cov]); c = np.cumsum(wgt[cov][order]) / wsum
    pct = {f'p{p}': float(ycode[cov][order][np.searchsorted(c, p / 100.0)]) for p in (1, 5, 25, 50, 75, 95, 99)}
    up = (ana.lat > 0) & cov; dn = (ana.lat <= 0) & cov
    grid = np.zeros((GRID_H, GRID_W)); gcov = np.zeros((GRID_H, GRID_W))
    ys = (np.arange(SPH_H) * GRID_H // SPH_H)[:, None] * np.ones((1, SPH_W), int); xs = (np.arange(SPH_W) * GRID_W // SPH_W)[None, :] * np.ones((SPH_H, 1), int)
    np.add.at(grid, (ys, xs), y * wgt); np.add.at(gcov, (ys, xs), wgt)
    grid = np.where(gcov > 0, grid / np.maximum(gcov, 1e-12), np.nan)
    return dict(
        coverage=float((wgt.sum() / ana.solid.sum())),
        mean_lin=float((y * wgt).sum() / wsum), mean_lin_rgb=[float(v) for v in rgb],
        luma_code_percentiles=pct, mean_luma_code=float((ycode * wgt).sum() / wsum),
        clipped_frac=float(((ycode > 0.98) * wgt).sum() / wsum), crushed_frac=float(((ycode < 0.02) * wgt).sum() / wsum),
        sky_mean_lin=float((y * ana.solid * up).sum() / max((ana.solid * up).sum(), 1e-9)),
        ground_mean_lin=float((y * ana.solid * dn).sum() / max((ana.solid * dn).sum(), 1e-9)),
        grid_mean_lin=[[None if np.isnan(v) else round(float(v), 4) for v in row] for row in grid])


def analyse(osv, every=10):
    """Exposure statistics for a clip (README 5.9): returns the exposure.json body."""
    a = argparse.Namespace(osv=osv, every=every)
    tel = read_frames(a.osv); exp = read_exposure(a.osv); pts = video_pts(a.osv, 0)
    ana = Analyser(a.osv); frames = []
    for (k, cm), (k2, cs) in zip(decode_stream(a.osv, 1, a.every), decode_stream(a.osv, 0, a.every)):
        assert k == k2
        sph, cov = ana.sphere(cm, cs, tel['quat'][k])
        st = stats_for(sph, cov, ana)
        lm, lm_cov = ana.lens_mean(cm, ana.master, ana.occl_m); ls, ls_cov = ana.lens_mean(cs, ana.slave, ana.occl_s)
        e = {name: exp[name] for name in exp}
        frames.append(dict(
            frame=int(k), t_s=round(float(pts[k] - pts[0]), 4),
            camera=dict(iso=[float(e['djmd3']['iso'][k]), float(e['djmd4']['iso'][k])],
                        shutter_den=[int(e['djmd3']['shutter_den'][k]), int(e['djmd4']['shutter_den'][k])],
                        colour_temp_k=[int(e['djmd3']['ct'][k]), int(e['djmd4']['ct'][k])],
                        exposure_index_ev=[float(np.log2(e['djmd3']['iso'][k] / e['djmd3']['shutter_den'][k])),
                                           float(np.log2(e['djmd4']['iso'][k] / e['djmd4']['shutter_den'][k]))]),
            sphere=st,
            lens=dict(master_mean_lin_rgb=[float(v) for v in lm], slave_mean_lin_rgb=[float(v) for v in ls],
                      master_area_frac=lm_cov, slave_area_frac=ls_cov)))
    ml = np.array([f['sphere']['mean_lin'] for f in frames]); med = float(np.median(ml))
    for f in frames:   # informational only: the naive gain that would bring this sample to the clip median
        f['naive_gain_to_clip_median'] = round(med / f['sphere']['mean_lin'], 4)
    doc = dict(
        schema_version=SCHEMA_VERSION, tool='strata360.exposure_stats',
        source=dict(file=os.path.basename(a.osv), camera='dji_osmo_360', colour_mode='normal',
                    note='colour_mode read from StreamMeta.4 (empty = 0 = Normal); frame indices are decoded-frame indices (match telemetry rows)'),
        time_note='t_s is clip-relative seconds (pts minus first pts). Absolute UTC = clip.json start_utc + t_s. Not stored here (README 5.1).',
        sampling=dict(every_n_frames=a.every, n_samples=len(frames), source_frames=int(len(pts)), lens_analysis_px=LENS_PX,
                      sphere_px=[SPH_W, SPH_H], grid_cells=[GRID_W, GRID_H], grid_cell_deg=15),
        definitions=dict(
            mean_lin='solid-angle weighted mean of BT.709 linear luma over the covered sphere (0..1, diffuse white about 0.9)',
            luma_code_percentiles='percentiles of BT.709-encoded luma (0..1), solid-angle weighted',
            clipped_frac='fraction of sphere with encoded luma > 0.98; crushed_frac: < 0.02',
            sky_mean_lin='mean linear luma above the horizon of the STABILISED world frame (latitude > 0); ground_mean_lin below',
            grid_mean_lin='rows top (north, +90..+75 deg) to bottom; columns lon -180..+180 in the stabilised world frame (yaw datum = DJI P matrix); null = not covered',
            exposure_index_ev='log2(ISO / shutter denominator) per lens (relative sensor exposure; higher = more light gathered)',
            naive_gain_to_clip_median='informational: clip median mean_lin divided by this sample mean_lin; NOT applied anywhere'),
        summary=dict(mean_lin_min=float(ml.min()), mean_lin_median=med, mean_lin_max=float(ml.max()),
                     mean_lin_range_stops=float(np.log2(ml.max() / ml.min())),
                     exposure_index_ev_range=[float(np.ptp([f['camera']['exposure_index_ev'][0] for f in frames])), float(np.ptp([f['camera']['exposure_index_ev'][1] for f in frames]))]),
        frames=frames)
    return doc


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('osv'); ap.add_argument('out'); ap.add_argument('--every', type=int, default=10)
    a = ap.parse_args(); t0 = time.time()
    doc = analyse(a.osv, a.every)
    with open(a.out, 'w') as fh: json.dump(doc, fh, indent=1)
    print(f'wrote {a.out}: {doc["sampling"]["n_samples"]} samples in {time.time() - t0:.1f} s; mean_lin range {doc["summary"]["mean_lin_min"]:.3f}..{doc["summary"]["mean_lin_max"]:.3f} ({doc["summary"]["mean_lin_range_stops"]:.2f} stops)')


if __name__ == '__main__':
    main()
