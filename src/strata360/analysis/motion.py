"""Per-clip motion analysis from the camera telemetry alone (`motion.json`; no video decoding, so it is fast).

Series at 5 Hz (clip-relative seconds): smoothed heading of the front lens, heading rate, angular speed, hand-shake (high-frequency angular speed),
elevation of the front lens, and accelerometer energy. Summary: steadiness (0..1, used later as the `steady` content feature), fraction of
stationary time, total turn, and running cadence (dominant 1.2-3.5 Hz component of the accelerometer, if clear).

Rotation matrices follow the renderer's convention: d_body = M d_E, with M = B^T R(q)^T P^T (README stabilisation model)."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from strata360.osv.calib import quat_to_R, imu_offsets
from strata360.osv.telemetry import read_frames

SCHEMA_VERSION = 1
OUT_HZ = 5.0


def analyse(osv):
    T = read_frames(osv); P, B = imu_offsets()
    t = (T['ts_us'] - T['ts_us'][0]) / 1e6; n = len(t)
    Ms = np.array([B.T @ quat_to_R(q).T @ P.T for q in T['quat']])
    dt = np.maximum(np.diff(t), 1e-3)
    rel = np.einsum('nij,nkj->nik', Ms[1:], Ms[:-1])                                   # rotation from frame i to i+1
    ang = np.degrees(np.arccos(np.clip((np.trace(rel, axis1=1, axis2=2) - 1) / 2, -1, 1))) / dt
    ang = np.append(ang, ang[-1]); fps = (n - 1) / max(t[-1], 1e-6)
    d = np.einsum('nji,j->ni', Ms, np.array([0.0, 1.0, 0.0]))                          # front lens axis in the upright frame
    elev = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    hor = np.hypot(d[:, 0], d[:, 1]); raw = np.arctan2(d[:, 0], d[:, 1]); ok = hor > 0.25
    if ok.any():
        idx = np.arange(n); head = np.interp(idx, idx[ok], np.unwrap(raw[ok]))
    else:
        head = np.zeros(n)
    head_s = gaussian_filter1d(head, 1.0 * fps, mode='nearest'); hrate = np.degrees(np.gradient(head_s, t))
    slow = gaussian_filter1d(ang, 0.5 * fps, mode='nearest'); shake = np.sqrt(gaussian_filter1d((ang - slow) ** 2, 0.5 * fps, mode='nearest'))
    acc = np.linalg.norm(T['acc'], axis=1); accd = acc - gaussian_filter1d(acc, 1.0 * fps, mode='nearest')
    acc_e = np.sqrt(gaussian_filter1d(accd ** 2, 0.5 * fps, mode='nearest'))
    cad_hz, cad_strength = None, 0.0
    if n > 3 * fps:
        x = accd - accd.mean(); f = np.fft.rfftfreq(n, 1 / fps); s = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2; b = (f >= 1.2) & (f <= 3.5)
        if b.any() and s[(f >= 0.3)].sum() > 0:
            k = np.argmax(s * b); cad_strength = float(s[k] / s[(f >= 0.3) & (f <= 8)].sum()); cad_hz = float(f[k]) if cad_strength > 0.15 else None
    from strata360.gps.clock import step_windows
    sw = step_windows(acc, t, fps)
    out_t = np.arange(0, t[-1], 1 / OUT_HZ); at = lambda a: np.interp(out_t, t, a)
    steady = float(np.exp(-np.median(shake) / 25.0))
    return dict(schema=SCHEMA_VERSION, duration_s=float(t[-1]), frames=int(n), fps=float(fps),
                series=dict(t=out_t.round(3).tolist(), heading_deg=np.degrees(at(head_s)).round(2).tolist(), heading_rate_dps=at(hrate).round(2).tolist(),
                            ang_speed_dps=at(slow).round(2).tolist(), shake_dps=at(shake).round(2).tolist(), front_elev_deg=at(elev).round(2).tolist(),
                            acc_energy=at(acc_e).round(4).tolist()),
                steps=dict(t=sw[:, 0].round(2).tolist(), hz=sw[:, 1].round(3).tolist(), strength=sw[:, 2].round(3).tolist()),      # 4 s windows every 1 s: the wearer's step rhythm
                summary=dict(steady=round(steady, 3), median_shake_dps=round(float(np.median(shake)), 2), median_ang_speed_dps=round(float(np.median(slow)), 2),
                             stationary_fraction=round(float((slow < 4.0).mean()), 3), total_turn_deg=round(float(np.abs(np.diff(head_s)).sum() * 180 / np.pi), 1),
                             cadence_hz=cad_hz, cadence_strength=round(cad_strength, 3)))
