

def test_blocking_is_graded_by_what_the_words_cover():
    from strata360.edit import title_design as TD
    spec = dict(elements=[dict(text='HALFWAY', font='anton', size=0.2, x=0.5, y=0.5, fill=dict(type='solid', c1='#ffffff'))], timing=dict(start_s=0.0, end_s=2.0)); times = [0.5, 1.0]
    none = TD.blocking(spec, times, [[], []], [[], []], [], 2.0); assert none['score'] == 0.0 and none['what'] == ''
    face = TD.blocking(spec, times, [[(0.45, 0.45, 0.55, 0.55)]] * 2, [[]] * 2, [], 2.0); assert face['face'] > 0.3 and face['score'] > 3.0 and 'face' in face['what']
    edge = TD.blocking(spec, times, [[(0.0, 0.0, 0.05, 0.05)]] * 2, [[]] * 2, [], 2.0); assert edge['score'] == 0.0
    text = TD.blocking(spec, times, [[], []], [[], []], [(0.4, 0.4, 0.6, 0.6)], 2.0); assert text['text'] > 0.3 and text['score'] > 0
