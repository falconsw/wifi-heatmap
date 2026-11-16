#!/usr/bin/env python3
"""A simple signal model fitted to one round, and where to put the access points.

    RSSI = P0 − 10·n·log10(distance) − W·walls        (from the strongest access point)

P0, n and W are fitted to the round's measurements (least squares on a grid). Its leave-one-out error says how far an
estimate can be off. Then the access points named in --move are moved, and --add new ones placed, to raise the average of
the weakest points the most. "After" = measured + (model with the new layout − model with the current one): only the
change comes from the model. This is an estimate, not a measurement: measure again after moving.

    python3 model.py --round tur-1 --move ap2           # where should ap2 go?
    python3 model.py --round tur-1 --add 1              # where should one new access point go?
    python3 model.py --round tur-1 --move ap2 --add 1
then  python3 heatmap.py --suggestion  draws the estimate.
"""
import argparse, itertools, math
import numpy as np
from wifimap import last_values, load_plan, path, room_at, room_name, round_aps, rounds, save_json, text, lang_of, walls

GRID = np.array(list(itertools.product(np.arange(-55, -19, 1.0), np.arange(1.5, 4.6, 0.1), np.arange(0, 12.5, 0.5))))
STEP = 0.5          # candidate spacing, metres


def features(plan, pts, ap):
    """[[distance m, walls] per point] for one access point position."""
    return np.array([[max(math.dist((p['x'], p['y']), ap), 0.5), walls(plan, ap, (p['x'], p['y']))] for p in pts])


def single(theta, f):
    p0, n, w = theta
    return p0 - 10 * n * np.log10(f[:, 0]) - w * f[:, 1]


def fit(fs, meas):
    """fs: [points × aps × 2], meas: [points] → best (P0, n, W) on GRID."""
    pr = GRID[:, None, None, 0] - 10 * GRID[:, None, None, 1] * np.log10(fs[None, :, :, 0]) - GRID[:, None, None, 2] * fs[None, :, :, 1]
    err = ((pr.max(2) - meas[None, :]) ** 2).sum(1)
    return tuple(GRID[int(np.argmin(err))])


def main():
    ap = argparse.ArgumentParser(description='Signal model and access point placement')
    ap.add_argument('--data', default='data')
    ap.add_argument('--round', help='round to fit (default: the first one)')
    ap.add_argument('--move', nargs='*', default=[], help='ids of access points that may move (e.g. ap2)')
    ap.add_argument('--add', type=int, default=0, help='how many new access points to place')
    ap.add_argument('--lang')
    a = ap.parse_args()
    L = lang_of(a.lang)
    plan = load_plan(a.data)
    if not plan: raise SystemExit(text(L, 'no_plan', host='localhost', port=8777))
    rnd = a.round or (rounds(a.data) or [''])[0]
    vals = last_values(a.data, rnd)
    pts = [p for p in plan['points'] if p['n'] in vals]
    if len(pts) < 6: raise SystemExit(text(L, 'few_points', round=rnd, n=len(pts)))
    aps = round_aps(a.data, plan, rnd)
    if not aps: raise SystemExit(text(L, 'no_ap'))
    ids = [x['id'] for x in aps]
    for m in a.move:
        if m not in ids: raise SystemExit(text(L, 'unknown_ap', id=m, ids=', '.join(ids)))
    meas = np.array([vals[p['n']] for p in pts])

    fs = np.stack([features(plan, pts, (x['x'], x['y'])) for x in aps], 1)      # points × aps × 2
    theta = fit(fs, meas)
    print(text(L, 'fit', p0=theta[0], n=theta[1], w=theta[2]))
    loo = [np.max([single(fit(np.delete(fs, i, 0), np.delete(meas, i)), fs[i:i + 1, j])[0] for j in range(len(aps))]) - meas[i] for i in range(len(pts))]
    rmse = float(np.sqrt(np.mean(np.square(loo))))
    print(text(L, 'rmse', v=rmse))

    free = len(a.move) + a.add
    if not free:
        save_json(path(a.data, 'model.json'), {'round': rnd, 'theta': list(map(float, theta)), 'loo_rmse': round(rmse, 1)})
        raise SystemExit(text(L, 'nothing_free'))
    x0, y0 = min(r[0] for q in plan['rooms'] for r in q['rects']), min(r[1] for q in plan['rooms'] for r in q['rects'])
    x1, y1 = max(r[0] + r[2] for q in plan['rooms'] for r in q['rects']), max(r[1] + r[3] for q in plan['rooms'] for r in q['rects'])
    cands = [(x, y) for x in np.arange(x0 + STEP / 2, x1, STEP) for y in np.arange(y0 + STEP / 2, y1, STEP) if room_at(plan, x, y)]
    S = np.array([single(theta, features(plan, pts, c)) for c in cands])                      # candidates × points
    now = np.max([single(theta, fs[:, j]) for j in range(len(aps))], 0)
    fixed = [j for j, x in enumerate(aps) if x['id'] not in a.move]
    base = np.max([single(theta, fs[:, j]) for j in fixed], 0) if fixed else np.full(len(pts), -200.0)
    k = min(5, len(pts))

    def score(model):
        after = np.minimum(-30, meas + model - now)
        return np.sort(after)[:k].mean() + after.mean() * 0.01, after

    if free == 1:
        best = max(((score(np.maximum(base, S[i]))[0], (i,)) for i in range(len(cands))))
    elif free == 2:
        best = (-1e9, None)
        for i in range(len(cands)):
            m = np.maximum(np.maximum(base[None, :], S[i][None, :]), S[i:])
            after = np.minimum(-30, meas[None, :] + m - now[None, :])
            sc = np.sort(after, 1)[:, :k].mean(1) + after.mean(1) * 0.01
            j = int(np.argmax(sc))
            if sc[j] > best[0]: best = (sc[j], (i, i + j))
    else:   # greedy: one at a time, then each re-placed once given the others
        pick = []
        for _ in range(free):
            m0 = np.max([base] + [S[q] for q in pick], 0)
            pick.append(max(range(len(cands)), key=lambda i: score(np.maximum(m0, S[i]))[0]))
        for t in range(free):
            others = np.max([base] + [S[q] for u, q in enumerate(pick) if u != t], 0)
            pick[t] = max(range(len(cands)), key=lambda i: score(np.maximum(others, S[i]))[0])
        best = (None, tuple(pick))
    chosen = [cands[i] for i in best[1]]
    after = score(np.max([base] + [S[i] for i in best[1]], 0))[1]

    out, it = [], iter(chosen)
    print(text(L, 'suggest', what=', '.join(a.move + ([f'+{a.add}'] if a.add else []))))
    for x in aps:
        if x['id'] in a.move:
            nx, ny = next(it)
            out.append({**x, 'x': nx, 'y': ny, 'from': [x['x'], x['y']]})
            print('  ' + text(L, 'ap_move', name=x['name'], x=x['x'], y=x['y'], nx=nx, ny=ny, room=room_name(plan, room_at(plan, nx, ny))))
        else:
            out.append(x)
    for i, (nx, ny) in enumerate(it, 1):
        out.append({'id': f'new{i}', 'name': f'+{i}', 'x': nx, 'y': ny, 'new': True})
        print('  ' + text(L, 'ap_add', x=nx, y=ny, room=room_name(plan, room_at(plan, nx, ny))))
    print(text(L, 'before_after', k=k, a=np.sort(meas)[:k].mean(), b=np.sort(after)[:k].mean(), c=meas.mean(), d=after.mean()))
    save_json(path(a.data, 'suggestion.json'), {
        'round': rnd, 'theta': list(map(float, theta)), 'loo_rmse': round(rmse, 1), 'aps': out,
        'measured': {p['n']: v for p, v in zip(pts, meas.tolist())},
        'values': {p['n']: round(float(v), 1) for p, v in zip(pts, after)}})


if __name__ == '__main__':
    main()
