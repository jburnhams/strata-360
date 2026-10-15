import numpy as np
import pytest

from strata360.edit import title_design as TD




def test_blocking_is_graded_by_what_the_words_cover():
    from strata360.edit import title_design as TD
    spec = dict(elements=[dict(text='HALFWAY', font='anton', size=0.2, x=0.5, y=0.5, fill=dict(type='solid', c1='#ffffff'))], timing=dict(start_s=0.0, end_s=2.0)); times = [0.5, 1.0]
    none = TD.blocking(spec, times, [[], []], [[], []], [], 2.0); assert none['score'] == 0.0 and none['what'] == ''
    face = TD.blocking(spec, times, [[(0.45, 0.45, 0.55, 0.55)]] * 2, [[]] * 2, [], 2.0); assert face['face'] > 0.3 and face['score'] > 3.0 and 'face' in face['what']
    edge = TD.blocking(spec, times, [[(0.0, 0.0, 0.05, 0.05)]] * 2, [[]] * 2, [], 2.0); assert edge['score'] == 0.0
    text = TD.blocking(spec, times, [[], []], [[], []], [(0.4, 0.4, 0.6, 0.6)], 2.0); assert text['text'] > 0.3 and text['score'] > 0


class TestPaletteStyling:
    """Display words and small text are dressed differently from the clip's palette (title_design.style_from_palette)."""
    @staticmethod
    def swatches():
        from strata360.analysis import palette as P
        blocks = np.zeros((60, 120, 3), np.uint8); blocks[:, :60] = (30, 110, 140); blocks[:, 60:] = (200, 150, 60)
        return P.analyse_pixels([blocks] * 2)['scheme']['swatches']

    @staticmethod
    def el(size, font='barlow_cond_light', tracking=0.02):
        return dict(text='WORD', font=font, size=size, tracking=tracking, fill=dict(type='solid', c1='#ffffff', c2='#ffffff', angle=90.0), stroke=dict(w=0.0, color='#101010'), shadow=dict(blur=0.012, opacity=0.45, dy=0.004), glow=dict(r=0.0, color='#ffffff', opacity=0.0))

    def dark_area(self): return np.full((200, 3), 0.05, np.float32)

    def bright_area(self): return np.full((200, 3), 0.92, np.float32)

    def test_small_text_gets_a_high_contrast_tint_a_scaled_outline_a_sturdier_font_and_the_accent_glow(self):
        from strata360.render import titles as TT
        sw = self.swatches(); e = self.el(0.07); note = TD.style_from_palette(e, sw, self.dark_area(), [], 1, 2)
        lum = TT.luminance(TT.hex_rgb(e['fill']['c1'])); assert (lum + 0.05) / (TT.luminance((0.05, 0.05, 0.05)) + 0.05) >= TD.SMALL_AA - 0.05 and 'small text' in note
        assert e['stroke']['w'] == pytest.approx(0.045 * 0.07, abs=1e-4) and e['font'] == 'barlow_cond_bold' and e['tracking'] >= 0.1 and e['glow']['opacity'] >= 0.4 and e['glow']['r'] > 0 and e['shadow']['opacity'] >= 0.75

    def test_display_words_keep_a_saturated_hue_with_a_heavier_outline_and_their_font(self):
        sw = self.swatches(); e = self.el(0.22, font='anton'); note = TD.style_from_palette(e, sw, self.dark_area(), [], 0, 2)
        assert 'display text' in note and e['font'] == 'anton' and e['glow']['opacity'] == 0.0 and e['stroke']['w'] == pytest.approx(0.03 * 0.22, abs=1e-4)
        assert any(x['hex'] == e['fill']['c1'] and x['tone'].startswith('mid') for x in sw)

    def test_the_outline_grows_with_the_size_up_to_a_limit(self):
        sw = self.swatches(); small, smaller = self.el(0.09), self.el(0.03)
        TD.style_from_palette(small, sw, self.dark_area(), [], 1, 2); TD.style_from_palette(smaller, sw, self.dark_area(), [], 1, 2)
        assert smaller['stroke']['w'] == 0.0015 and small['stroke']['w'] > smaller['stroke']['w'] and small['stroke']['w'] <= 0.005

    def test_the_size_that_counts_as_small_is_the_threshold(self):
        sw = self.swatches(); just_under, just_over = self.el(TD.SMALL_EM - 0.001), self.el(TD.SMALL_EM)
        assert 'small text' in TD.style_from_palette(just_under, sw, self.dark_area(), [], 1, 2) and 'display text' in TD.style_from_palette(just_over, sw, self.dark_area(), [], 1, 2)

    def test_on_a_bright_area_small_text_goes_deep_not_pale(self):
        from strata360.render import titles as TT
        sw = self.swatches(); e = self.el(0.07); TD.style_from_palette(e, sw, self.bright_area(), [], 1, 2); assert TT.luminance(TT.hex_rgb(e['fill']['c1'])) < 0.2

    def test_when_no_tint_reaches_the_target_a_tinted_neutral_with_the_best_contrast_is_used(self):
        sw = self.swatches(); mid = np.full((200, 3), 0.45, np.float32); e = self.el(0.07); note = TD.style_from_palette(e, sw, mid, [], 1, 2)
        assert 'small text' in note and e['fill']['c1'] in {x['hex'] for x in sw if x['role'] == 'neutral'}

    def test_a_font_that_is_already_sturdy_is_kept(self):
        e = self.el(0.07, font='inter'); TD.style_from_palette(e, self.swatches(), self.dark_area(), [], 1, 2); assert e['font'] == 'inter'

    def test_enforce_applies_it_by_size_to_a_two_line_card(self):
        frame = np.zeros((90, 160, 3), np.uint8); frame[:] = (20, 30, 50); from strata360.analysis import palette as P
        blocks = np.zeros((60, 120, 3), np.uint8); blocks[:, :60] = (30, 110, 140); blocks[:, 60:] = (200, 150, 60); doc = P.analyse_pixels([blocks] * 2)
        spec = dict(elements=[dict(text='DAY 2', font='anton', size=0.22, x=0.5, y=0.4), dict(text='KILOMETRE 84', font='barlow_cond_light', size=0.07, x=0.5, y=0.62)])
        out, notes = TD.enforce(spec, [dict(role='title', text='DAY 2'), dict(role='meta', text='KILOMETRE 84')], [frame], [3.0], [[]], 6.0, palette=doc)
        big, small = out['elements']; assert any('display text' in n for n in notes) and any('small text' in n for n in notes) and small['font'] == 'barlow_cond_bold' and big['font'] == 'anton' and big['stroke']['w'] > small['stroke']['w']
