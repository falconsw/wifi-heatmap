#!/usr/bin/env python3
"""Heat maps from the measurements: <data>/out/*.png, all on the same colour scale (-85 … -35 dBm).

Between the measured points the signal is estimated by inverse distance weighting (IDW); points in the same room count
4× as much, so the colour changes at walls instead of bleeding through them.

    python3 heatmap.py                     # one map per round
    python3 heatmap.py --compare tur-1 tur-2   # before / after side by side
    python3 heatmap.py --diff tur-1 tur-2      # change per point, dB
    python3 heatmap.py --suggestion        # the estimate model.py wrote (suggestion.json)
"""
import argparse, json, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from wifimap import HI, LO, bounds, label_at, lang_of, last_values, load_plan, path, room_at, round_aps, rounds, text

PX = 80             # pixels per metre
M = 0.6             # margin around the plan, metres
TOP = 90            # title band, pixels
INK, WHITE, YELLOW = (17, 19, 24), (245, 242, 234), (255, 194, 58)
STOPS = np.array([[214, 48, 49], [240, 140, 40], [246, 214, 70], [80, 200, 120], [40, 170, 110]], float)


def font(size):
    for f in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/Library/Fonts/Arial Bold.ttf', 'DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf'):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


class Canvas:
    """Pixel grid of one plan: metres ↔ pixels and the room under every pixel."""

    def __init__(self, plan):
        self.plan = plan
        x0, y0, x1, y1 = bounds(plan)
        self.x0, self.y0 = x0 - M, y0 - M
        self.w, self.h = int((x1 - x0 + 2 * M) * PX), int((y1 - y0 + 2 * M) * PX)
        mask = Image.new('I', (self.w, self.h), 0)
        d = ImageDraw.Draw(mask)
        self.rid = {r['id']: i for i, r in enumerate(plan['rooms'], 1)}
        for r in plan['rooms']:
            for x, y, w, h in r['rects']: d.rectangle([*self.px(x, y), *self.px(x + w, y + h)], fill=self.rid[r['id']])
        self.room = np.array(mask)
        self.gx, self.gy = np.meshgrid((np.arange(self.w) + .5) / PX + self.x0, (np.arange(self.h) + .5) / PX + self.y0)

    def px(self, x, y):
        return (x - self.x0) * PX, (y - self.y0) * PX

    def field(self, values):
        pts = {p['n']: p for p in self.plan['points']}
        num, den = np.zeros((self.h, self.w)), np.zeros((self.h, self.w))
        for n, v in values.items():
            p = pts.get(n)
            if not p: continue
            same = self.room == self.rid.get(room_at(self.plan, p['x'], p['y']), -1)
            wgt = 1 / ((self.gx - p['x']) ** 2 + (self.gy - p['y']) ** 2 + .2) ** 1.5 * np.where(same, 4.0, 1.0)
            num += wgt * v; den += wgt
        return num / den


def colour(v):
    k = np.clip((v - LO) / (HI - LO), 0, 1) * (len(STOPS) - 1)
    i = np.minimum(k.astype(int), len(STOPS) - 2); f = (k - i)[..., None]
    return (STOPS[i] * (1 - f) + STOPS[i + 1] * f).astype(np.uint8)


def diff_colour(v):
    k = np.clip(v / 12, -1, 1)[..., None]          # −12 … +12 dB
    neg, pos, mid = np.array([214, 48, 49.]), np.array([40, 170, 110.]), np.array([40, 46, 70.])
    return np.where(k < 0, mid * (1 + k) + neg * -k, mid * (1 - k) + pos * k).astype(np.uint8)


def draw_map(plan, values, aps, title, diff=False):
    c = Canvas(plan)
    img = np.full((c.h, c.w, 3), INK, np.uint8)
    if values:
        rgb = (diff_colour if diff else colour)(c.field(values))
        img[c.room > 0] = rgb[c.room > 0]
    else:
        img[c.room > 0] = (35, 38, 47)
    im = Image.new('RGB', (c.w, c.h + TOP), INK)
    im.paste(Image.fromarray(img), (0, TOP))
    g = ImageDraw.Draw(im)
    o = lambda x, y: (c.px(x, y)[0], c.px(x, y)[1] + TOP)
    # walls: where the room under a pixel changes (no line between the pieces of one room)
    room = c.room
    edge = np.zeros_like(room, bool)
    edge[1:, :] |= room[1:, :] != room[:-1, :]; edge[:, 1:] |= room[:, 1:] != room[:, :-1]
    for _ in range(2): edge = edge | np.roll(edge, 1, 0) | np.roll(edge, 1, 1)
    im.paste(Image.new('RGB', (c.w, c.h), WHITE), (0, TOP), Image.fromarray((edge * 255).astype(np.uint8)))
    for r in plan['rooms']:
        g.text(o(*label_at(r)), r['name'], fill=WHITE, font=font(20), anchor='mm', stroke_width=3, stroke_fill=INK)
    for a in aps:
        x, y = o(a['x'], a['y'])
        if a.get('from'):
            fx, fy = o(*a['from'])
            g.line([(fx, fy), (x, y)], fill=WHITE, width=4)
            g.rounded_rectangle([fx - 14, fy - 14, fx + 14, fy + 14], 6, outline=WHITE, width=3)
        edge = YELLOW if a.get('new') or a.get('from') else INK
        g.rounded_rectangle([x - 18, y - 18, x + 18, y + 18], 8, fill=WHITE, outline=edge, width=5)
    for p in plan['points']:
        x, y = o(p['x'], p['y'])
        v = values.get(p['n'])
        g.ellipse([x - 26, y - 26, x + 26, y + 26], fill=INK, outline=WHITE, width=3)
        g.text((x, y), str(p['n']) if v is None else (f'{v:+.0f}' if diff else f'{v:.0f}'), fill=WHITE, font=font(22), anchor='mm')
    g.text((24, TOP / 2), title, fill=WHITE, font=font(34), anchor='lm')
    return im


def stats(values):
    v = np.array(list(values.values()))
    return v.mean(), min(values, key=values.get), v.min()


def legend(width, diff=False):
    im = Image.new('RGB', (width, 70), INK)
    g = ImageDraw.Draw(im)
    bar = (diff_colour if diff else colour)(np.linspace(-12, 12, 300) if diff else np.linspace(LO, HI, 300))
    im.paste(Image.fromarray(np.repeat(bar[None, :, :], 14, 0)), (90, 28))
    lo, hi = ('-12 dB', '+12 dB') if diff else (f'{LO:.0f} dBm', f'{HI:.0f} dBm')
    g.text((80, 35), lo, fill=WHITE, font=font(18), anchor='rm'); g.text((400, 35), hi, fill=WHITE, font=font(18), anchor='lm')
    return im


def stack(*parts):
    w = max(p.width for p in parts)
    out = Image.new('RGB', (w, sum(p.height for p in parts)), INK)
    y = 0
    for p in parts: out.paste(p, (0, y)); y += p.height
    return out


def main():
    ap = argparse.ArgumentParser(description='Wi-Fi heat maps')
    ap.add_argument('--data', default='data')
    ap.add_argument('--round', nargs='*', help='rounds to draw (default: all)')
    ap.add_argument('--compare', nargs=2, metavar=('BEFORE', 'AFTER'))
    ap.add_argument('--diff', nargs=2, metavar=('BEFORE', 'AFTER'))
    ap.add_argument('--suggestion', action='store_true', help="draw model.py's estimate (suggestion.json)")
    ap.add_argument('--lang')
    a = ap.parse_args()
    L = lang_of(a.lang)
    plan = load_plan(a.data)
    if not plan: raise SystemExit(text(L, 'no_plan', host='localhost', port=8777))
    out = path(a.data, 'out'); os.makedirs(out, exist_ok=True)

    def values(rnd):
        v = last_values(a.data, rnd)
        if not v: raise SystemExit(text(L, 'no_rows', round=rnd))
        return v

    def write(im, name):
        f = os.path.join(out, name); im.save(f); print(text(L, 'written', path=f))

    if a.compare:
        ims, lines = [], []
        for rnd in a.compare:
            v = values(rnd); avg, n, low = stats(v)
            ims.append(draw_map(plan, v, round_aps(a.data, plan, rnd), text(L, 'map_title', round=rnd, avg=avg)))
            lines.append(f"{rnd}: {text(L, 'average', v=avg)}, {text(L, 'worst', n=n, v=low)}")
        both = Image.new('RGB', (ims[0].width * 2 + 30, ims[0].height), INK)
        both.paste(ims[0], (0, 0)); both.paste(ims[1], (ims[0].width + 30, 0))
        write(stack(both, legend(both.width)), f'compare-{a.compare[0]}-{a.compare[1]}.png')
        print('\n'.join(lines))
    elif a.diff:
        va, vb = values(a.diff[0]), values(a.diff[1])
        d = {n: vb[n] - va[n] for n in va if n in vb}
        im = draw_map(plan, d, round_aps(a.data, plan, a.diff[1]), text(L, 'diff_title', a=a.diff[0], b=a.diff[1]), diff=True)
        write(stack(im, legend(im.width, diff=True)), f'diff-{a.diff[0]}-{a.diff[1]}.png')
    elif a.suggestion:
        s = json.load(open(path(a.data, 'suggestion.json'), encoding='utf-8'))
        v = {int(k): x for k, x in s['values'].items()}
        im = draw_map(plan, v, s['aps'], text(L, 'estimate_title', avg=stats(v)[0]))
        write(stack(im, legend(im.width)), f"suggestion-{s['round']}.png")
    else:
        for rnd in a.round or rounds(a.data):
            v = values(rnd); avg, n, low = stats(v)
            im = draw_map(plan, v, round_aps(a.data, plan, rnd), text(L, 'map_title', round=rnd, avg=avg))
            write(stack(im, legend(im.width)), f'{rnd}.png')
            print(f"  {text(L, 'average', v=avg)}, {text(L, 'worst', n=n, v=low)}")


if __name__ == '__main__':
    main()
