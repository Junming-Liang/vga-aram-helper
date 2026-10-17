"""Explicit original presentation-only card geometry, never recognition evidence."""
from types import SimpleNamespace


def seed_badge_geometry(overlay, names=None):
    names = names or [card['name'] for card in overlay.cards]
    candidates = [dict(name=name, box=[[90+i*270,240],[180+i*270,240],
                   [180+i*270,270],[90+i*270,270]]) for i,name in enumerate(names)]
    geometry = SimpleNamespace(rects=((.05,.35,.25,.55),(.35,.35,.25,.55),(.65,.35,.25,.55)),
                               size=(900,600), space='frame')
    assert overlay.set_candidate_geometry(candidates,{'width':900,'height':600},(0,0,1,1),geometry)
