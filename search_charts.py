#!/usr/bin/env python3
"""Search the downloaded weekly charts in ./charts for a song and/or artist.

Matches are case-insensitive substrings, so --artist "bee gees" finds
"Bee Gees" and --song love finds every title containing "love". Give --song,
--artist or both (both must match). Entries for the same song (same rules as
build_plif.py: title + lead artist, typos corrected) are grouped together,
with each chart file it appears in and its position that week.

With --score N, each song also gets a score the way build_plif.py's
--min-points counts it with --top N: each week at position P <= N earns
N + 1 - P points (#1 = N ... #N = 1), and weeks below #N earn nothing.

Usage: search_charts.py [--song TEXT] [--artist TEXT] [--top 50] [--score N]
                        [--start 1976] [--end 2005]
"""
import argparse
from pathlib import Path

from build_plif import ARTIST_TYPOS, TITLE_TYPOS, key, parse

def main():
    ap = argparse.ArgumentParser(
        description='Find which weekly chart files a song or artist appears in, and at what position.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  search_charts.py --song "like a virgin"
  search_charts.py --artist madonna --start 1984 --end 1985
  search_charts.py --song "hold on" --artist wilson --top 40
  search_charts.py --artist survivor --score 40
      score each song the way build_plif.py does by default (#1 = 40 ... #40 = 1)
""")
    ap.add_argument('--song', help='text to find in the song title (case-insensitive)')
    ap.add_argument('--artist', help='text to find in the artist name (case-insensitive)')
    ap.add_argument('--top', type=int, default=50,
                    help='only look at chart positions 1..TOP (default: %(default)s, every row)')
    ap.add_argument('--score', type=int, metavar='N',
                    help='score each song: N + 1 - position points per week in the top N (#1 = N ... #N = 1)')
    ap.add_argument('--start', type=int, default=1976, help='first year to search (default: %(default)s)')
    ap.add_argument('--end', type=int, default=2005, help='last year to search (default: %(default)s)')
    args = ap.parse_args()
    if not args.song and not args.artist:
        ap.error('give --song, --artist, or both')
    song, artist = (args.song or '').lower(), (args.artist or '').lower()

    base = Path(__file__).resolve().parent
    files = sorted(p for p in (base / 'charts').glob('[12][0-9][0-9][0-9]-*.html')
                   if args.start <= int(p.name[:4]) <= args.end)
    found = {}          # key -> {name, artist, weeks: [(file, pos)]}, in order of first appearance
    for f in files:
        for pos, t, a in parse(f, args.top):
            t, a = TITLE_TYPOS.get(t, t), ARTIST_TYPOS.get(a, a)     # so "Suvivor" weeks match "survivor"
            if song in t.lower() and artist in a.lower():
                s = found.setdefault(key(t, a), {'name': t, 'artist': a, 'weeks': []})
                s['weeks'].append((f.name, pos))

    if not found:
        print('no matches')
        return
    pts = lambda pos: max(args.score + 1 - pos, 0) if args.score else 0
    for s in found.values():
        weeks = s['weeks']
        peak = min(pos for _, pos in weeks)
        score = f', score {sum(pts(pos) for _, pos in weeks)}' if args.score else ''
        print(f"{s['name']} - {s['artist']}: {len(weeks)} weeks, peak #{peak}{score}")
        for name, pos in weeks:
            print(f'  {name}\t#{pos}' + (f'\t{pts(pos)} pts' if args.score else ''))
    print(f'{len(found)} songs, {sum(len(s["weeks"]) for s in found.values())} chart entries')

if __name__ == '__main__':
    main()
