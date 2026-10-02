"""Per-project calibration of the VLM scenery scores to 0..10."""
import numpy as np
from strata360.edit import quality_scale as Q


def test_the_range_of_the_project_is_stretched_to_0_10_and_order_is_kept():
    raw = [2, 3, 3, 5, 5, 5, 5, 6, 6, 6, 6, 6, 7]; s = Q.fit(raw); n = Q.apply(s, np.array(raw, float))
    assert s['lo'] == 3.0 and not s['widened'] and n.min() == 0.0 and n.max() == 10.0 and np.all(np.diff(n) >= 0)       # the 10th to 95th percentile cover 0..10; clipped outside


def test_a_uniformly_mediocre_race_is_not_stretched_into_noise():
    raw = [5, 5, 5, 6, 5, 5, 6, 5, 5, 5]; s = Q.fit(raw)
    assert s['widened'] and s['hi'] - s['lo'] == Q.MIN_SPREAD and 3.0 < Q.apply(s, 5.0) < 7.0                              # a 5 stays in the middle; one point is not 10 marks


def test_a_sunny_race_and_a_wet_race_each_use_the_full_scale_but_keep_raw_scores_apart():
    wet = [2, 3, 5, 5, 5, 6, 6, 6]; sunny = [5, 6, 7, 7, 8, 8, 9, 9]
    sw, ss = Q.fit(wet), Q.fit(sunny)
    assert Q.apply(sw, 6.0) > 8 and Q.apply(ss, 6.0) < 3                                                                    # the same raw 6 is a top shot in one race and a weak one in the other
    assert ss['lo'] > sw['lo'] and ss['hi'] > sw['hi']                                                                    # the fitted ranges keep the raw difference, so absolute judgements can use them


def test_missing_values_are_ignored_and_no_data_is_the_identity_scale():
    s = Q.fit([None, 4, 6, float('nan'), 8]); assert s['n'] == 3
    ident = Q.fit([]); assert Q.apply(ident, 7.0) == 7.0
