

def test_a_window_that_goes_back_in_the_clip_does_not_say_the_same_words_again():
    from strata360.audio import mix
    a = dict(clip='c', role='clip', clip_start_s=10.0, dur_s=4.0)
    assert abs(mix.replayed_s(a, dict(clip='c', role='clip', clip_start_s=13.84, dur_s=3.0)) - 0.16) < 1e-6          # starts 0.16 s before a's end
    assert mix.replayed_s(a, dict(clip='c', role='clip', clip_start_s=14.0, dur_s=3.0)) == 0.0                         # the same stretch go on
    assert mix.replayed_s(a, dict(clip='c', role='clip', clip_start_s=20.0, dur_s=3.0)) == 0.0                         # apart
    assert mix.replayed_s(a, dict(clip='c', role='clip', clip_start_s=5.0, dur_s=3.0)) == 0.0                          # earlier than a began
    assert mix.replayed_s(a, dict(clip='d', role='clip', clip_start_s=13.0, dur_s=3.0)) == 0.0 and mix.replayed_s(a, dict(clip='c', role='broll', clip_start_s=13.0, dur_s=3.0)) == 0.0
