#!/usr/bin/env python3
"""Build a Playlisty .plif from downloaded weekly charts in ./charts.

Takes positions 1..TOP (default 40) from every weekly chart between the given
years, de-duplicates songs (same title + artist), and orders them by the date
they first entered the Top 40.

Album names come from albums/albums.json (see lookup_albums.py) when present.

Usage: build_plif.py [--top 40] [--start 1976] [--end 2005]
                     [--caption "GenX Radio"] [--description "..."] [-o genx-radio.plif]
"""
import argparse, html, json, re, sys
from pathlib import Path

ROW_RE = re.compile(r'<tr[^>]*>\s*<td>(\d+)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>', re.S)

def clean(s):
    s = html.unescape(re.sub(r'<[^>]+>', '', s))
    return re.sub(r'\s+', ' ', s).strip()

def song_title(t):
    # drop site annotations like "[re-release]"
    return re.sub(r'\s*\[[^\]]*\]', '', t).strip()

ASCII = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
                       '\u2010': '-', '\u2011': '-', '\u2013': '-', '\u2014': '-', '\u2026': '...'})

def load_albums(base):
    f = base / 'albums' / 'albums.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}

def key(title, artist):
    # compare on the lead artist only, so "X" and "X ft. Y" for the same title collapse
    lead = re.split(r'\s+(?:&|and|with|feat\.?|ft\.?|featuring|duet with|x|vs\.?)\s+|,', artist, flags=re.I)[0]
    norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    return norm(title), norm(lead)

def parse(path, top):
    rows = []
    for pos, t, a in ROW_RE.findall(path.read_text(encoding='utf-8', errors='replace')):
        if int(pos) <= top:
            rows.append((int(pos), song_title(clean(t)), clean(a)))
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=40)
    ap.add_argument('--start', type=int, default=1976)
    ap.add_argument('--end', type=int, default=2005)
    ap.add_argument('--caption', default='GenX Radio')
    ap.add_argument('--description', default='Top 40 charting hits from 1976 to 2005')
    ap.add_argument('-o', '--output', default='genx-radio.plif')
    args = ap.parse_args()

    base = Path(__file__).resolve().parent
    files = sorted(p for p in (base / 'charts').glob('[12][0-9][0-9][0-9]-*.html')
                   if args.start <= int(p.name[:4]) <= args.end)
    albums = load_albums(base)
    seen, rows, empty = set(), [], []
    for f in files:
        entries = parse(f, args.top)
        if len(entries) < args.top:
            empty.append(f'{f.stem} ({len(entries)} rows)')
        for _, title, artist in sorted(entries):
            k = key(title, artist)
            if k in seen:
                continue
            seen.add(k)
            album = albums.get(f'{title}\t{artist}', {}).get('album', '').translate(ASCII)
            rows.append({"identifiers": {}, "album": album, "name": title, "artist": artist})

    plif = {
        "playlists": [{
            "destination": "Playlist",
            "folders": [],
            "identifiers": {},
            "rows": rows,
            "description": args.description,
            "type": "Tracks",
            "caption": args.caption,
            "curator": None,
        }],
        "app_id": "com.obdura.playlistimport",
        "app_version": "3.1",
    }
    out = base / args.output
    out.write_text(json.dumps(plif, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'{len(files)} charts, {len(rows)} unique songs, '
          f'{sum(1 for r in rows if r["album"])} with albums -> {out}')
    if empty:
        print(f'WARNING: {len(empty)} charts had fewer than {args.top} rows: ' + ', '.join(empty[:20]), file=sys.stderr)

if __name__ == '__main__':
    main()
