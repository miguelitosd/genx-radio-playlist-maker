#!/usr/bin/env python3
"""Look up the original album for every song in genx-radio.plif via MusicBrainz.

Steps:
  1. For each (title, artist) row, search MusicBrainz recordings (official releases)
     and cache a trimmed list of candidate release groups in albums/mb_cache.jsonl.
     Cached songs are never re-fetched, so this is safe to stop and re-run.
  2. Pick the earliest album by that artist the song appeared on (see pick()).
  3. Write albums/albums.json: {"title\\tartist": {"album", "date", "source", ...}}

build_plif.py fills in the album field from albums/albums.json.

Usage: lookup_albums.py [--plif genx-radio.plif] [--fallback OLD.plif] [--offline]
  --offline   don't query MusicBrainz, only re-pick from the cache
"""
import argparse, json, re, sys, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CACHE = BASE / 'albums' / 'mb_cache.jsonl'
OUT = BASE / 'albums' / 'albums.json'
UA = 'genx-radio-plif/1.0'
API = 'https://musicbrainz.org/ws/2/recording'

# ---------- normalisation ----------

def fold(s):
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace('&', ' and ')
    return re.sub(r'[^a-z0-9]', '', s)

def norm_title(t):
    t = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', t)  # drop "(Remix)", "[Live]" etc.
    return fold(t)

def lead_artist(a):
    return re.split(r'\s+(?:&|and|with|feat\.?|ft\.?|featuring|duet with|x|vs\.?)\s+|,', a, flags=re.I)[0].strip()

def norm_artist(a):
    a = fold(a)
    return a[3:] if a.startswith('the') and len(a) > 6 else a

def artist_match(want, names):
    w = norm_artist(want)
    for n in names:
        n = norm_artist(n)
        if not n or not w:
            continue
        if n == w or (min(len(n), len(w)) >= 4 and (w in n or n in w)):
            return True
    return False

def credit_names(credits):
    out = []
    for c in credits or []:
        out.append(c.get('name', ''))
        out.append(c.get('artist', {}).get('name', ''))
    return out

# ---------- MusicBrainz ----------

def mb_query(q):
    url = API + '?' + urllib.parse.urlencode({'query': q, 'fmt': 'json', 'limit': 100})
    for attempt in range(12):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (503, 502, 500, 429):   # MB's global limiter returns 503 when busy
                time.sleep(min(60, 2 + attempt * 5))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(min(60, 5 + attempt * 5))
    raise RuntimeError(f'MusicBrainz kept failing for: {q}')

def esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')

def candidates(resp, title, artist):
    """Trim a search response to release groups whose recording matches title+artist."""
    want_t = norm_title(title)
    lead = lead_artist(artist)
    groups = {}
    for rec in resp.get('recordings', []):
        rt = norm_title(rec.get('title', ''))
        full_ok = fold(rec.get('title', '')) == fold(title)   # "(Pride) In The..." vs "Pride (In the...)"
        if not full_ok and (not rt or not (rt == want_t or (len(want_t) >= 6 and (rt.startswith(want_t) or want_t.startswith(rt))))):
            continue
        rec_artists = credit_names(rec.get('artist-credit'))
        if not (artist_match(lead, rec_artists) or artist_match(artist, rec_artists)):
            continue
        for rel in rec.get('releases', []):
            if rel.get('status') != 'Official':
                continue
            rg = rel.get('release-group', {})
            gid = rg.get('id')
            if not gid:
                continue
            date = rel.get('date', '') or ''
            rel_artists = credit_names(rel.get('artist-credit'))
            g = groups.setdefault(gid, {
                'id': gid, 'title': rg.get('title') or rel.get('title'),
                'type': rg.get('primary-type'), 'secondary': rg.get('secondary-types', []),
                'artist': (rel.get('artist-credit') or [{}])[0].get('name', ''),
                # search results sometimes omit a release's credit: assume the recording artist
                'by_artist': (not any(rel_artists)) or artist_match(lead, rel_artists)
                             or artist_match(artist, rel_artists), 'date': ''})
            if date and (not g['date'] or date < g['date']):
                g['date'] = date
    return list(groups.values())

# Typos, abbreviations and nicknames in the chart site's data -> MusicBrainz names
ARTIST_FIXES = {
    'ELO': 'Electric Light Orchestra', 'NKOTB': 'New Kids on the Block', 'K.C.': 'KC',
    'E.U.': 'Experience Unlimited', 'The Carptenters': 'Carpenters', 'Suvivor': 'Survivor',
    'Orchestral Manuevers In The Dark': 'Orchestral Manoeuvres in the Dark',
    'Lindsay Buckingham': 'Lindsey Buckingham', 'Vanessa Wiliams': 'Vanessa Williams',
    'K-Ci Hailey of Jodeci': 'K-Ci Hailey', 'Mason Betha': 'Mase',
    'Snoop Doggy Dogg': 'Snoop Dogg', 'Big Punisher ft. Joe': 'Big Pun ft. Joe',
    'Henhouse Five Plus Too': 'Ray Stevens', 'Tami Show': 'The Tami Show',
}
TITLE_FIXES = {
    'Tbe Best Things In Life Are Free': 'The Best Things in Life Are Free',
    'Jigga My N****': 'Jigga My Nigga', 'F**k It (I Don\'t Want You Back)': 'Fuck It (I Don\'t Want You Back)',
    'Down A** Chick': 'Down Ass Chick', 'Sign \'O\' The Times': 'Sign o the Times',
}

def fix_artist(a):
    a = ARTIST_FIXES.get(a, a)
    for k, v in ARTIST_FIXES.items():
        if a.startswith(k + ' '):
            a = v + a[len(k):]
    return re.sub(r'\s*"[^"]*"\s*', ' ', a).strip()     # Missy "Misdemeanor" Elliott -> Missy Elliott

def title_variants(title):
    title = TITLE_FIXES.get(title, title)
    out = [title,
           re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', title).strip(),       # brackets dropped
           re.sub(r'\s+', ' ', re.sub(r'[\(\)\[\]]', ' ', title)).strip()]  # brackets kept, unwrapped
    if '/' in title:                                                      # double A-side
        out += [t.strip() for t in title.split('/') if t.strip()]
    seen, res = set(), []
    for t in out:
        if t and t not in seen:
            seen.add(t); res.append(t)
    return res

def search(title, artist):
    """Run queries from most to least specific, merging matching release groups,
    until an album-tier candidate turns up. Returns (queries used, candidates)."""
    artist = fix_artist(artist)
    lead = lead_artist(artist)
    titles = title_variants(title)
    queries = [f'recording:"{esc(t)}" AND artist:"{esc(lead)}" AND status:official' for t in titles]
    queries.append(f'recording:({esc(titles[1] if len(titles) > 1 else titles[0])}) AND artist:({esc(lead)})')
    if lead != artist:
        queries.append(f'recording:({esc(titles[0])}) AND artist:({esc(artist)})')  # full credit
    merged, used = {}, []
    for q in queries:
        used.append(q)
        resp = mb_query(q)
        time.sleep(1.1)
        for t in titles:
            for c in candidates(resp, t, artist):
                g = merged.get(c['id'])
                if g is None:
                    merged[c['id']] = c
                    continue
                g['by_artist'] = g['by_artist'] or c['by_artist']
                if c['date'] and (not g['date'] or c['date'] < g['date']):
                    g['date'] = c['date']
        if any(c['date'] and pick_tier(c) == 0 for c in merged.values()):
            break
    return ' || '.join(used), list(merged.values())

# ---------- selection ----------

# "Soundtracks" that just reuse existing hits (telenovelas, foreign dubs, TV-series
# compilations): treated like Various Artists compilations, i.e. ignored.
SOUNDTRACK_SKIP = re.compile('|'.join([
    'Internacional', 'Malha[cç][aã]o', 'Sol de Ver[aã]o', 'De Quina Pra Lua', 'Uga Uga',
    'Despedida de solteiro', 'Kommissar Rex', 'unendliche Geschichte', 'Manta Manta', 'Unsere Schule',
    'Fresh Prince', 'Smallville', 'Dawson', '90210: The College Years', 'That[’\']s So Raven', 'Sailor Moon',
    'Asterix', 'Men Behaving Badly', 'Tubes 20', 'WWF', 'Fox Sports', '^Hamilton:', '^Hercule$', '^Hércules$',
    '^Le Bossu', 'Leijonakuningas', 'Løvernes Konge', 'Lejonkungen', 'Løvenes konge', 'König der Löwen',
    'Le Roi Lion', 'Rey Le[oó]n', 'Rei Le[aã]o', 'Re Leone', 'Kr[oó]l lew', 'Leeuwen?koning', 'Summer Night Fever', '^The Stud$', 'Yesterday[’\']s Hero',
    '^Drive Me Crazy$', 'Skatetown', 'URGH', 'Hip Hopera', 'Otro d[ií]a m[aá]s sin verte',
]), re.I)

def non_latin(t):
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in t)   # e.g. Korean/Japanese OSTs

def skipped_soundtrack(c):
    t = c['title'] or ''
    # (no by_artist exception: foreign editions often lack credits and get assumed to be the artist's)
    return 'Soundtrack' in c['secondary'] and bool(SOUNDTRACK_SKIP.search(t) or non_latin(t))

BAD_SECONDARY = {'Live', 'Remix', 'DJ-mix', 'Interview', 'Demo', 'Spokenword', 'Mixtape/Street'}

def pick_tier(c):
    if skipped_soundtrack(c):
        return None
    sec = set(c['secondary'])
    if c['type'] == 'Album' and not (sec & BAD_SECONDARY):
        if c['by_artist'] and not sec:
            return 0                       # artist's own studio album
        if c['by_artist'] or 'Soundtrack' in sec:
            return 0                       # artist's compilation, or a soundtrack
    if c['type'] == 'EP' and c['by_artist'] and not (sec & BAD_SECONDARY):
        return 1
    if c['type'] == 'Album' and c['by_artist']:
        return 2                           # live/remix album by the artist
    return None

def pick(cands):
    best = None
    for c in cands:
        t = pick_tier(c) if c['date'] else None
        if t is None or not c['date']:
            continue
        # Earliest year wins within the best tier. Many releases only have a year, so
        # same-year ties go soundtrack > studio album > artist compilation, then full date.
        sec = set(c['secondary'])
        # (a "soundtrack" credited to the artist themselves gets no special preference)
        prio = 0 if ('Soundtrack' in sec and not c['by_artist']) else (2 if 'Compilation' in sec else 1)
        k = (t, c['date'][:4], prio, bool(sec), c['date'])
        if best is None or k < best[0]:
            best = (k, c)
    if best is None:
        return None
    return best[1]

# ---------- main ----------

def fmt_dur(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f'{h}h{m:02d}m' if h else f'{m}m{s:02d}s'

def load_cache():
    cache = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding='utf-8').splitlines():
            if line.strip():
                e = json.loads(line)
                cache[e['key']] = e
    return cache

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plif', default=str(BASE / 'genx-radio.plif'))
    ap.add_argument('--fallback', default=str(Path.home() / 'genx-radio.plif'),
                    help='older .plif whose album names are used when MusicBrainz finds nothing')
    ap.add_argument('--offline', action='store_true')
    args = ap.parse_args()

    rows = json.loads(Path(args.plif).read_text(encoding='utf-8'))['playlists'][0]['rows']
    CACHE.parent.mkdir(exist_ok=True)
    cache = load_cache()

    fallback = {}
    fb = Path(args.fallback)
    if fb.exists():
        for r in json.loads(fb.read_text(encoding='utf-8'))['playlists'][0]['rows']:
            if r.get('album'):
                fallback[(norm_title(r['name']), norm_artist(lead_artist(r['artist'])))] = r['album']

    todo = [r for r in rows if f"{r['name']}\t{r['artist']}" not in cache]
    if todo and not args.offline:
        print(f'{len(todo)} songs to look up ({len(rows) - len(todo)} cached)', flush=True)
        last = time.time()
        with CACHE.open('a', encoding='utf-8') as fh:
            for i, r in enumerate(todo, 1):
                key = f"{r['name']}\t{r['artist']}"
                try:
                    q, cands = search(r['name'], r['artist'])
                except RuntimeError as err:   # not cached, so a re-run retries it
                    print(f'SKIPPED {key!r}: {err}', flush=True)
                    continue
                e = {'key': key, 'query': q, 'candidates': cands}
                fh.write(json.dumps(e, ensure_ascii=False) + '\n'); fh.flush()
                cache[key] = e
                if i % 100 == 0:
                    now = time.time()
                    per100, last = now - last, now
                    left = len(todo) - i
                    eta = per100 * left / 100
                    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {i}/{len(todo)}  "
                          f"last 100 took {fmt_dur(per100)}  {left} left  "
                          f"ETA {fmt_dur(eta)} (~{time.strftime('%H:%M', time.localtime(now + eta))})",
                          flush=True)

    result, stats = {}, {'musicbrainz': 0, 'fallback': 0, 'none': 0}
    for r in rows:
        key = f"{r['name']}\t{r['artist']}"
        c = pick(cache.get(key, {}).get('candidates', []))
        if c:
            result[key] = {'album': c['title'], 'date': c['date'], 'source': 'musicbrainz',
                           'release_group': c['id'], 'kind': ' + '.join([c['type']] + c['secondary'])}
            stats['musicbrainz'] += 1
        elif (alb := fallback.get((norm_title(r['name']), norm_artist(lead_artist(r['artist']))))):
            result[key] = {'album': alb, 'source': 'old-plif'}
            stats['fallback'] += 1
        else:
            stats['none'] += 1
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'albums: {stats} -> {OUT}')

if __name__ == '__main__':
    main()
