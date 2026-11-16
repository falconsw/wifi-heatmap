#!/usr/bin/env python3
"""Wi-Fi measurement server (standard library only).

The iPhone shortcut sends each measurement to POST /m; it is appended to <data>/measurements.csv. Open
http://<this-mac>:8777/ on the phone or the Mac: the Measure tab shows the plan with the points measured in the current
round, the Plan tab draws the plan (rooms, measurement points, router/access points).

    python3 server.py                 # data in ./data
    python3 server.py --data example  # the synthetic example

Shortcut body (JSON): p = point number, rssi = readings (a list or one per line), noise, ch, bssid. The BSSID is never
stored: only a 4-character hash of it, enough to tell which access point the phone was on.
"""
import argparse, csv, hashlib, json, os, re, socket, statistics, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from wifimap import FIELDS, lang_of, load_plan, path, rounds, rows, save_json, text

HERE = os.path.dirname(os.path.abspath(__file__))
BG_TYPES = {b'\x89PNG': ('background.png', 'image/png'), b'\xff\xd8\xff': ('background.jpg', 'image/jpeg')}


def nums(v):
    """A Shortcuts value as numbers: a list, or text with one number per line."""
    if isinstance(v, list): v = '\n'.join(map(str, v))
    return [float(x.replace(',', '.')) for x in re.findall(r'-?\d+(?:[.,]\d+)?', str(v))] if v is not None else []


def lan_ip():
    if sys.platform == 'darwin':
        for iface in ('en0', 'en1'):
            ip = subprocess.run(['ipconfig', 'getifaddr', iface], capture_output=True, text=True).stdout.strip()
            if ip: return ip
    try:   # the address the system would use to reach the outside: no packet is sent
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('192.0.2.1', 9)); return s.getsockname()[0]
    except OSError:
        return 'localhost'


class Handler(BaseHTTPRequestHandler):
    data = 'data'
    lang = 'tr'
    url = ''

    def send(self, code, body, ctype='text/plain; charset=utf-8'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(b)

    def body(self):
        return self.rfile.read(int(self.headers.get('Content-Length') or 0))

    def current_round(self):
        p = path(self.data, 'round.txt')
        return open(p, encoding='utf-8').read().strip() if os.path.exists(p) else 'tur-1'

    def state(self):
        rnd = self.current_round()
        names = rounds(self.data)
        return {'round': rnd, 'rounds': names if rnd in names else names + [rnd], 'plan': load_plan(self.data),
                'rows': [r for r in rows(self.data) if r['round'] == rnd], 'lang': self.lang, 'url': self.url}

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self.send(200, open(os.path.join(HERE, 'web', 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
        if self.path.startswith('/api/state'):
            return self.send(200, json.dumps(self.state(), ensure_ascii=False), 'application/json; charset=utf-8')
        if self.path.startswith('/background'):
            plan = load_plan(self.data) or {}
            name = (plan.get('background') or {}).get('file')
            if name and os.path.exists(path(self.data, name)):
                return self.send(200, open(path(self.data, name), 'rb').read(), 'image/png' if name.endswith('.png') else 'image/jpeg')
        self.send(404, 'not found')

    def do_POST(self):
        raw = self.body()
        if self.path == '/m': return self.measurement(raw.decode('utf-8', 'replace'))
        if self.path == '/api/plan':
            save_json(path(self.data, 'plan.json'), json.loads(raw))
            return self.send(200, 'ok')
        if self.path == '/api/round':
            name = re.sub(r'[^\w.-]+', '-', raw.decode('utf-8').strip(), flags=re.U).strip('-')[:40]
            if name: open(path(self.data, 'round.txt'), 'w', encoding='utf-8').write(name)
            return self.send(200, self.current_round())
        if self.path == '/api/background':
            kind = next((v for k, v in BG_TYPES.items() if raw.startswith(k)), None)
            if not kind: return self.send(400, 'PNG or JPEG only')
            open(path(self.data, kind[0]), 'wb').write(raw)
            return self.send(200, kind[0])
        self.send(404, 'not found')

    def measurement(self, raw):
        L = self.lang
        try:
            d = json.loads(raw)
        except ValueError:
            return self.send(400, f"{text(L, 'bad_json')}: {raw[:120]}")
        p, r = int((nums(d.get('p')) or [0])[0]), nums(d.get('rssi'))
        if not p or not r: return self.send(400, f"{text(L, 'no_point')}: {raw[:160]}")
        plan = load_plan(self.data)
        if plan and p not in [q['n'] for q in plan['points']]: return self.send(400, text(L, 'unknown_point', n=p))
        one = lambda k: (nums(d.get(k)) or [''])[0]
        bssid = str(d.get('bssid', '')).strip().lower()
        rnd = self.current_round()
        row = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'round': rnd, 'point': p, 'rssi': round(statistics.median(r), 1),
               'rssi_raw': ' '.join(str(int(x)) for x in r), 'noise': one('noise'), 'tx': one('tx'), 'rx': one('rx'),
               'channel': int(one('ch')) if one('ch') != '' else '', 'ap': hashlib.sha1(bssid.encode()).hexdigest()[:4] if bssid else ''}
        csv_path = path(self.data, 'measurements.csv')
        new = not os.path.exists(csv_path)
        with open(csv_path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, FIELDS)
            if new: w.writeheader()
            w.writerow(row)
        # keep where the access points stood during this round, so the model is fitted to the right layout later
        rp = path(self.data, 'rounds.json')
        saved = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}
        if rnd not in saved and plan:
            saved[rnd] = {'aps': plan.get('aps', []), 'started': row['time']}
            save_json(rp, saved)
        band = '5 GHz' if row['channel'] and row['channel'] > 14 else '2.4 GHz' if row['channel'] else ''
        msg = ' · '.join(x for x in [text(L, 'point', n=p, rssi=row['rssi']), band, f"AP {row['ap']}" if row['ap'] else '', rnd] if x)
        print(f"{row['time']} {msg} ({row['rssi_raw']})", flush=True)
        self.send(200, '✓ ' + msg)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Wi-Fi measurement server')
    ap.add_argument('--data', default='data', help='data folder (plan.json, measurements.csv)')
    ap.add_argument('--port', type=int, default=8777)
    ap.add_argument('--lang', help='tr or en (default: WIFIHEATMAP_LANG or tr)')
    a = ap.parse_args()
    os.makedirs(a.data, exist_ok=True)
    Handler.data, Handler.lang = a.data, lang_of(a.lang)
    url = Handler.url = f'http://{lan_ip()}:{a.port}'
    print(text(Handler.lang, 'server', url=url + '/'), flush=True)
    print(text(Handler.lang, 'shortcut_url', url=url), flush=True)
    ThreadingHTTPServer(('0.0.0.0', a.port), Handler).serve_forever()
