"""End-to-end smoke test of the renderer CLI at low resolution (about 20 s). Run: python spike/test_render_smoke.py [OSV]

Checks every mode, a keyframed segment with audio, colour tags, frame counts and the audio/video duration match.
Exists because the CLI once broke silently (an edit turned an argument definition into a comment)."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
OSV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'videos', 'CAM_20260221120007_0019_D.OSV')

def probe(path, entries):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', entries, '-of', 'json', path]))

def render(out, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'render4k.py'), OSV, out, '--size', '960x540', '--bitrate', '20M', *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout

def check(path, frames, audio=True, secs=None):
    v = probe(path, 'stream=codec_type,codec_name,profile,pix_fmt,width,height,nb_frames,color_space,color_transfer,color_primaries,color_range,codec_tag_string,duration')
    vs = [s for s in v['streams'] if s['codec_type'] == 'video'][0]; au = [s for s in v['streams'] if s['codec_type'] == 'audio']
    assert vs['codec_name'] == 'hevc' and vs['profile'] == 'Main 10' and vs['pix_fmt'] == 'yuv420p10le' and vs['codec_tag_string'] == 'hvc1', vs
    assert (vs['width'], vs['height']) == (960, 540), vs
    assert (vs['color_space'], vs['color_transfer'], vs['color_primaries'], vs['color_range']) == ('bt709', 'bt709', 'bt709', 'tv'), vs
    assert int(vs['nb_frames']) == frames, (vs['nb_frames'], frames)
    if audio:
        assert len(au) == 1, 'audio stream missing'
        assert abs(float(au[0]['duration']) - float(vs['duration'])) < 0.06, (au[0]['duration'], vs['duration'])
    else:
        assert not au

def main():
    tmp = tempfile.mkdtemp()
    for name, extra in (('world', ['--mode', 'world', '--yaw', '10', '--pitch', '5']), ('heading', ['--mode', 'heading', '--heading-tau', '0.5']),
                        ('body', ['--mode', 'body', '--target', 'user', '--fov', '100'])):
        out = f'{tmp}/{name}.mp4'; render(out, '--frames', '12', '--audio', 'none', *extra); check(out, 12, audio=False); print('ok  ', name)
    out = f'{tmp}/seg.mp4'; render(out, '--path', os.path.join(HERE, 'example_path.json'), '--start', '1.0', '--end', '2.0', '--audio', 'aac')
    check(out, 51, audio=True); print('ok   keyframed segment 1.0-2.0 s with audio')
    out = f'{tmp}/full.mp4'; render(out, '--mode', 'world', '--frames', '30', '--audio', 'copy'); check(out, 30, audio=True); print('ok   audio copy')
    print('render smoke test passed')

if __name__ == '__main__':
    main()
