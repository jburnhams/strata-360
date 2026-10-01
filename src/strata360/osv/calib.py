"""Read DJI Osmo 360 factory lens calibration from the OSV djmd clip header, and project with it.

Calibration lives in the first djmd packet: StreamMeta.6 = PanoDewarpParams, 24 slots of 264 bytes.
Per-slot fields (found by decoding, cross-checked with OpenOSV docs/GEOMETRY.md and FORMAT.md):
  1,2 fx,fy   3,4 cx,cy   5..8 k1..k4   15 k5   10,11 width,height (3840)
  12,13,14 Euler angles (deg)   28 = camera extrinsic quaternion (w,x,y,z), d_lens = R(q) d_body
Model (Kannala-Brandt, 5 terms):  theta_d = theta*(1 + k1 th^2 + k2 th^4 + k3 th^6 + k4 th^8 + k5 th^10)
  u = cx + fx*theta_d*cos(phi),  v = cy + fy*theta_d*sin(phi)
Body frame: X right, Y forward, Z up. Master lens looks along +Y, slave along -Y.
"""
import struct, numpy as np
from strata360.osv.pbdump import parse, packets, first_packet

def read_slots(osv_path, djmd_stream=3):
    pk = first_packet(osv_path, djmd_stream)
    sm = [v for f, w, v in parse(pk) if f == 2][0]
    f6 = [v for f, w, v in parse(sm) if f == 6][0]
    slots = {}
    for f, w, v in parse(f6):
        if w == 2 and len(v) == 264:
            d = {}
            for ff, ww, vv in parse(v):
                if ww == 5: d[ff] = struct.unpack('<f', vv)[0]
                elif ww == 2 and ff in (22, 23) and len(vv) == 56:
                    d['poly_x' if ff == 22 else 'poly_y'] = np.array(struct.unpack('<14f', vv))   # 14-point occlusion polygon (selfie-stick side)
                elif ww == 2 and ff == 28:
                    q = {a: struct.unpack('<f', c)[0] for a, b, c in parse(vv)}
                    d['q'] = np.array([q[1], q[2], q[3], q[4]])
            slots[f] = d
    return slots

def quat_to_R(q):
    q = np.asarray(q, dtype=np.float64); w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

import os as _os
_DATA = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'data')


def imu_offsets():
    """(P, B): constant matrices tying the IMU quaternion to DJI's upright frame and to the lens body frame (Osmo 360; fitted in M0, see docs/progress.md)."""
    return np.load(_os.path.join(_DATA, 'osmo360_imu_offsets.npy'))


class Lens:
    def __init__(self, slot):
        self.fx, self.fy, self.cx, self.cy = slot[1], slot[2], slot[3], slot[4]
        self.k = np.array([slot[5], slot[6], slot[7], slot[8], slot[15]])
        self.R = quat_to_R(slot['q'])
    def project(self, d_body, scale=1.0):
        """body-frame unit dirs (N,3) -> pixel (u,v) in the lens image at `scale`, plus theta (rad)."""
        d = np.einsum('nj,ij->ni', np.asarray(d_body, dtype=np.float64), self.R)   # einsum: avoids a broken Accelerate matmul seen on this Mac
        th = np.arccos(np.clip(d[:, 2], -1, 1)); phi = np.arctan2(d[:, 1], d[:, 0])
        thd = th * (1 + sum(self.k[i] * th ** (2 * (i + 1)) for i in range(5)))
        return (self.cx + self.fx * thd * np.cos(phi)) * scale, (self.cy + self.fy * thd * np.sin(phi)) * scale, th

    def rim_radius(self, theta_deg=97.59):
        """Radius in lens pixels of the edge of the usable image circle (where theta reaches `theta_deg`), the rim the stick polygon is closed out to."""
        th = np.radians(theta_deg); return float(self.fx * th * (1 + sum(self.k[i] * th ** (2 * (i + 1)) for i in range(5))))

    def edge_theta(self, radius_px=1900.0):
        th = np.linspace(0, np.pi, 4000); thd = th * (1 + sum(self.k[i] * th ** (2 * (i + 1)) for i in range(5)))
        r = self.fx * thd; ok = np.where(np.diff(r) > 0)[0]
        return th, r
