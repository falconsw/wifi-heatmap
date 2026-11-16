"""Shared pieces (standard library only): the data folder, the plan, wall counting, measurements and texts.

The plan is in metres. A room is one or more rectangles [x, y, w, h]; two rectangles of the same room (an L-shaped room)
have no wall between them. A wall is counted whenever a straight line passes from one room into another.
"""
import csv, json, math, os, re

LO, HI = -85.0, -35.0          # colour scale of every map, dBm (red … green)
FIELDS = ['time', 'round', 'point', 'rssi', 'rssi_raw', 'noise', 'tx', 'rx', 'channel', 'ap']

TEXTS = {
    'tr': {
        'title': 'Wi-Fi ısı haritası',
        'server': 'Wi-Fi ölçüm sunucusu: {url}',
        'shortcut_url': 'Kestirmeye yazılacak adres: {url}',
        'round': 'tur',
        'point': 'Nokta {n}: {rssi:.0f} dBm',
        'saved': 'Kaydedildi',
        'bad_json': 'JSON okunamadı',
        'no_point': 'Nokta numarası ya da RSSI yok',
        'unknown_point': 'Planda {n} numaralı nokta yok',
        'no_plan': 'Plan yok: önce http://{host}:{port}/ adresinde Plan sekmesinden çizin (ya da --data example)',
        'no_rows': '"{round}" turunda ölçüm yok',
        'average': 'ortalama {v:.1f} dBm',
        'worst': 'en zayıf: nokta {n}, {v:.0f} dBm',
        'map_title': '{round} · ortalama {avg:.1f} dBm',
        'diff_title': '{b} − {a} (dB)',
        'estimate_title': 'Tahmin (model, ölçüm değil) · ortalama {avg:.1f} dBm',
        'written': 'yazıldı: {path}',
        'fit': 'Model: P0 {p0:.0f} dBm, n {n:.1f}, duvar başına {w:.1f} dB',
        'rmse': 'Hata (birini dışarıda bırak): {v:.1f} dB. Tahminler bu kadar şaşabilir.',
        'few_points': 'Model için en az 6 ölçülmüş nokta gerekir ("{round}" turunda {n} var)',
        'no_ap': 'Planda modem/erişim noktası yok: Plan sekmesinde ekleyin',
        'suggest': 'Öneri ({what}):',
        'ap_move': '{name}: ({x:.1f}, {y:.1f}) m → ({nx:.1f}, {ny:.1f}) m, {room}',
        'ap_add': 'Yeni erişim noktası: ({x:.1f}, {y:.1f}) m, {room}',
        'before_after': 'En zayıf {k} noktanın ortalaması {a:.1f} → {b:.1f} dBm (tahmin), ev ortalaması {c:.1f} → {d:.1f} dBm (tahmin)',
        'unknown_ap': 'Planda "{id}" adlı erişim noktası yok. Olanlar: {ids}',
        'nothing_free': 'Taşınacak ya da eklenecek erişim noktası yok: --move ya da --add verin',
    },
    'en': {
        'title': 'Wi-Fi heat map',
        'server': 'Wi-Fi measurement server: {url}',
        'shortcut_url': 'Address to put in the shortcut: {url}',
        'round': 'round',
        'point': 'Point {n}: {rssi:.0f} dBm',
        'saved': 'Saved',
        'bad_json': 'Could not read the JSON',
        'no_point': 'No point number or RSSI',
        'unknown_point': 'The plan has no point {n}',
        'no_plan': 'No plan: draw one first in the Plan tab at http://{host}:{port}/ (or use --data example)',
        'no_rows': 'No measurements in round "{round}"',
        'average': 'average {v:.1f} dBm',
        'worst': 'weakest: point {n}, {v:.0f} dBm',
        'map_title': '{round} · average {avg:.1f} dBm',
        'diff_title': '{b} − {a} (dB)',
        'estimate_title': 'Estimate (model, not a measurement) · average {avg:.1f} dBm',
        'written': 'written: {path}',
        'fit': 'Model: P0 {p0:.0f} dBm, n {n:.1f}, {w:.1f} dB per wall',
        'rmse': 'Error (leave one out): {v:.1f} dB. Estimates can be off by about that much.',
        'few_points': 'The model needs at least 6 measured points (round "{round}" has {n})',
        'no_ap': 'The plan has no router/access point: add one in the Plan tab',
        'suggest': 'Suggestion ({what}):',
        'ap_move': '{name}: ({x:.1f}, {y:.1f}) m → ({nx:.1f}, {ny:.1f}) m, {room}',
        'ap_add': 'New access point: ({x:.1f}, {y:.1f}) m, {room}',
        'before_after': 'Average of the {k} weakest points {a:.1f} → {b:.1f} dBm (estimate), home average {c:.1f} → {d:.1f} dBm (estimate)',
        'unknown_ap': 'The plan has no access point "{id}". It has: {ids}',
        'nothing_free': 'Nothing to move or add: pass --move or --add',
    },
}


def lang_of(arg=None):
    lang = arg or os.environ.get('WIFIHEATMAP_LANG', 'tr')
    return lang if lang in TEXTS else 'tr'


def text(lang, key, **kw):
    s = TEXTS[lang][key].format(**kw)
    return re.sub(r'(?<=\d)\.(?=\d)', ',', s) if lang == 'tr' and key not in ('written', 'server', 'shortcut_url') else s   # Turkish decimal comma


def path(data, name):
    return os.path.join(data, name)


def load_plan(data):
    p = path(data, 'plan.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def save_json(file, obj):
    tmp = file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, file)


def room_at(plan, x, y):
    for r in plan['rooms']:
        for rx, ry, rw, rh in r['rects']:
            if rx <= x <= rx + rw and ry <= y <= ry + rh: return r['id']
    return None


def room_name(plan, rid):
    return next((r['name'] for r in plan['rooms'] if r['id'] == rid), '?')


def walls(plan, a, b):
    """Walls between a and b: how many times the straight line enters a different room."""
    n = max(int(math.dist(a, b) / 0.05), 2)
    count, prev = 0, room_at(plan, *a)
    for i in range(1, n + 1):
        t = i / n
        cur = room_at(plan, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        if cur is not None and prev is not None and cur != prev: count += 1
        if cur is not None: prev = cur
    return count


def bounds(plan):
    rs = [q for r in plan['rooms'] for q in r['rects']]
    return (min(x for x, _, _, _ in rs), min(y for _, y, _, _ in rs), max(x + w for x, _, w, _ in rs), max(y + h for _, y, _, h in rs))


def rows(data):
    p = path(data, 'measurements.csv')
    return list(csv.DictReader(open(p, encoding='utf-8'))) if os.path.exists(p) else []


def rounds(data):
    """Round names in the order they were first measured."""
    seen = []
    for r in rows(data):
        if r['round'] not in seen: seen.append(r['round'])
    return seen


def last_values(data, rnd):
    """{point: rssi} of a round; a point measured again keeps its last value."""
    out = {}
    for r in rows(data):
        if r['round'] == rnd: out[int(r['point'])] = float(r['rssi'])
    return out


def round_aps(data, plan, rnd):
    """The access points as they stood during a round (saved at its first measurement), else the plan's current ones."""
    p = path(data, 'rounds.json')
    saved = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return saved.get(rnd, {}).get('aps') or plan.get('aps', [])
