#!/usr/bin/env python3
"""Build a Playlisty .plif from downloaded weekly charts in ./charts.

Takes positions 1..TOP (default 40) from every weekly chart between the given
years, de-duplicates songs (same title + artist), and orders them by the date
they first entered the Top 40.

With --min-points N, each week on the chart scores (TOP + 1 - position) points
(with TOP=40: #1 = 40, #40 = 1), and only songs totalling at least N are kept.
Add --scores to also print the kept songs to stdout, highest score first, as
tab-separated score, song, artist, album (the summary then goes to stderr).
--allscores does the same but lists every song, with a marker line between the
kept songs and those that scored below N.

Album names come from albums/albums.json (see lookup_albums.py) when present.

Usage: build_plif.py [--top 40] [--start 1976] [--end 2005] [--min-points 0] [--scores | --allscores]
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

# Misspellings in the chart data. Used only when matching songs, so a typo'd week
# counts toward the correctly spelled song; the playlist shows the correct spelling.
TITLE_TYPOS = {
    'Tbe Best Things In Life Are Free': 'The Best Things In Life Are Free',
    'Spackavellie': 'Splackavellie',
}
ARTIST_TYPOS = {
    'Suvivor': 'Survivor', 'Lindsay Buckingham': 'Lindsey Buckingham',
    'Vanessa Wiliams': 'Vanessa Williams', 'Technotronci feat. Felly': 'Technotronic feat. Felly',
}

def is_typo(title, artist):
    return title in TITLE_TYPOS or artist in ARTIST_TYPOS

def key(title, artist):
    title, artist = TITLE_TYPOS.get(title, title), ARTIST_TYPOS.get(artist, artist)
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
    ap = argparse.ArgumentParser(
        description='Build a Playlisty .plif playlist from the weekly charts in ./charts.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
The playlist's name and description:
  --caption is the playlist's name, the title you see in the playlist list
  after importing. --description is the longer text shown under that name
  when you open the playlist.

examples:
  build_plif.py
      every Top 40 song from 1976-2005 -> genx-radio.plif
  build_plif.py --start 1985 --end 1989 --caption "Late 80s" \\
                --description "Top 40 hits, 1985-1989" -o late-80s.plif
      a smaller playlist for one stretch of years
  build_plif.py --top 10 --min-points 200
      only Top 10 entries, keeping songs that scored at least 200 points
  build_plif.py --min-points 300 --scores > scores.tsv
      also write the kept songs and their scores as TSV (summary goes to stderr)
  build_plif.py --min-points 300 --allscores | less
      see every song's score, with a marker line where the 300-point cutoff falls
""")
    ap.add_argument('--top', type=int, default=40,
                    help='use chart positions 1..TOP from each week (default: %(default)s)')
    ap.add_argument('--start', type=int, default=1976, help='first year to include (default: %(default)s)')
    ap.add_argument('--end', type=int, default=2005, help='last year to include (default: %(default)s)')
    ap.add_argument('--min-points', type=int, default=0,
                    help='keep only songs scoring at least this many points (#1 = TOP pts ... #TOP = 1 pt per week)')
    score_out = ap.add_mutually_exclusive_group()
    score_out.add_argument('--scores', action='store_true',
                           help='with --min-points, print kept songs and scores to stdout as TSV, highest first')
    score_out.add_argument('--allscores', action='store_true',
                           help='like --scores, but also list the songs below --min-points, after a marker line')
    ap.add_argument('--caption', default='GenX Radio',
                    help="the playlist's name (default: %(default)s)")
    ap.add_argument('--description', default='Top 40 charting hits from 1976 to 2005',
                    help="the playlist's description text, shown under its name (default: %(default)s)")
    ap.add_argument('-o', '--output', default='genx-radio.plif',
                    help='output file, relative to this script (default: %(default)s)')
    args = ap.parse_args()

    base = Path(__file__).resolve().parent
    files = sorted(p for p in (base / 'charts').glob('[12][0-9][0-9][0-9]-*.html')
                   if args.start <= int(p.name[:4]) <= args.end)
    albums = load_albums(base)
    songs, empty = {}, []          # key -> {name, artist, points}, in order of first appearance
    for f in files:
        entries = parse(f, args.top)
        if len(entries) < args.top:
            empty.append(f'{f.stem} ({len(entries)} rows)')
        for pos, title, artist in sorted(entries):
            k = key(title, artist)
            s = songs.get(k)
            if s is None:
                s = songs[k] = {'name': title, 'artist': artist, 'points': 0}
            elif is_typo(s['name'], s['artist']) and not is_typo(title, artist):
                s['name'], s['artist'] = title, artist      # prefer the correct spelling
            s['points'] += args.top + 1 - pos
    kept = [s for s in songs.values() if s['points'] >= args.min_points]
    rows, scored = [], []
    for s in songs.values():
        title, artist = s['name'], s['artist']
        album = albums.get(f'{title}\t{artist}', {}).get('album', '').translate(ASCII)
        if s['points'] >= args.min_points:
            rows.append({"identifiers": {}, "album": album, "name": title, "artist": artist})
        scored.append((s['points'], title, artist, album))

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
    show_scores = args.min_points and (args.scores or args.allscores)
    log = sys.stderr if show_scores else sys.stdout      # keep stdout clean TSV when printing scores
    if show_scores:
        marked = False
        for points, title, artist, album in sorted(scored, key=lambda r: -r[0]):
            if points < args.min_points:
                if not args.allscores:
                    break
                if not marked:
                    print(f'# ---- below {args.min_points} points: left out of the playlist ----')
                    marked = True
            print(f'{points}\t{title}\t{artist}\t{album}')
    if args.min_points:
        print(f'{len(songs) - len(kept)} of {len(songs)} songs scored under {args.min_points} points and were left out', file=log)
    print(f'{len(files)} charts, {len(rows)} unique songs, '
          f'{sum(1 for r in rows if r["album"])} with albums -> {out}', file=log)
    if empty:
        print(f'WARNING: {len(empty)} charts had fewer than {args.top} rows: ' + ', '.join(empty[:20]), file=sys.stderr)

if __name__ == '__main__':
    main()
