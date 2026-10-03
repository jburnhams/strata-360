

def test_the_planner_draws_a_big_climb_as_a_flyover_a_short_hop_or_clip_as_a_map_and_alternates_in_between():
    from strata360.edit import synthetic as SY
    big = dict(ascent_m=800, descent_m=300, distance_km=40); mid = dict(ascent_m=300, descent_m=250, distance_km=30); flat = dict(ascent_m=100, descent_m=80, distance_km=30); hop = dict(ascent_m=900, descent_m=900, distance_km=6)
    assert SY.choose_kind(big, 8) == 'flyover' and SY.choose_kind(big, 8, last='flyover') == 'flyover'          # the land is the story: always
    assert SY.choose_kind(big, 4) == 'map' and SY.choose_kind(flat, 10) == 'map' and SY.choose_kind(hop, 10) == 'map'      # too short, too flat, or a short hop
    assert SY.choose_kind(mid, 8) == 'flyover' and SY.choose_kind(mid, 8, last='flyover') == 'map' and SY.choose_kind(mid, 8, last='map') == 'flyover'      # in between: variety
    assert SY.make(dict(id='G01', t0=0.0, t1=3600.0), seconds=8)['by'] == 'planner' and SY.make(dict(id='G01', t0=0.0, t1=3600.0), seconds=8, by='user')['by'] == 'user'
