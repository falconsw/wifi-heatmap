#!/usr/bin/env python3
"""Writes the synthetic example in this folder: a made-up flat (plan.json) and made-up measurements (measurements.csv).
The values come from the model formula plus random noise. They are NOT a real measurement; they only let you try
heatmap.py and model.py before measuring your own home.

    python3 example/make_example.py
"""
import csv, math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wifimap import FIELDS, save_json, walls

HERE = os.path.dirname(os.path.abspath(__file__))
plan = {
    'size': [11.5, 9],
    'rooms': [
        {'id': 'r1', 'name': 'Yatak odası', 'rects': [[0, 0, 4, 4.5]]},
        {'id': 'r2', 'name': 'Oda 2', 'rects': [[4, 0, 3.5, 3.5]]},
        {'id': 'r3', 'name': 'Oda 3', 'rects': [[7.5, 0, 3.5, 3.5]]},
        {'id': 'r4', 'name': 'Koridor', 'rects': [[4, 3.5, 7, 1.2]]},
        {'id': 'r5', 'name': 'Mutfak', 'rects': [[0, 4.5, 4, 3.5]]},
        {'id': 'r6', 'name': 'Salon', 'rects': [[4, 4.7, 4.5, 3.8], [8.5, 7, 2.5, 1.5]]},
        {'id': 'r7', 'name': 'Banyo', 'rects': [[8.5, 4.7, 2.5, 2.3]]},
    ],
    'aps': [{'id': 'ap1', 'name': 'Modem', 'x': 4.5, 'y': 8.0}],
    'points': [{'n': n, 'x': x, 'y': y} for n, (x, y) in enumerate([
        (1, 1), (3, 3.5), (5, 1), (6.5, 2.75), (8.5, 1), (10, 2.75), (5.5, 4.1), (9.5, 4.1),
        (1, 5.5), (3, 7.25), (5.5, 6), (7.5, 7.75), (10, 7.75), (9.75, 5.75), (2, 2.25), (8, 5.5)], 1)],
    'background': None,
}
P0, N, W = -38.0, 2.5, 4.5          # the "true" values the noise is added to
rnd = random.Random(7)
ap = (plan['aps'][0]['x'], plan['aps'][0]['y'])
rows = []
for i, p in enumerate(plan['points']):
    true = P0 - 10 * N * math.log10(max(math.dist(ap, (p['x'], p['y'])), 0.5)) - W * walls(plan, ap, (p['x'], p['y'])) + rnd.gauss(0, 3)
    raw = sorted(round(true + rnd.gauss(0, 2)) for _ in range(3))
    rows.append({'time': f'2026-01-01 12:{i:02d}:00', 'round': 'ornek', 'point': p['n'], 'rssi': float(raw[1]), 'rssi_raw': ' '.join(map(str, raw)),
                 'noise': -92, 'tx': '', 'rx': '', 'channel': 36, 'ap': '0e5a'})
save_json(os.path.join(HERE, 'plan.json'), plan)
save_json(os.path.join(HERE, 'rounds.json'), {'ornek': {'aps': plan['aps'], 'started': rows[0]['time']}})
with open(os.path.join(HERE, 'measurements.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(rows)
print('example/plan.json, example/measurements.csv (synthetic)')
