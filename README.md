# GenX Radio

Builds one big playlist of every song that made the US Top 40 singles chart
between 1976 and 2005, in the order each song first charted. The output is a
`.plif` file that the Playlisty app (`com.obdura.playlistimport`) can import
into Apple Music or another streaming service.

Current result: 1,535 weekly charts → **5,587 unique songs**, 5,523 of them
with an album name.

## How it works

The pipeline has three steps:

```
musicchartsarchive.com ──fetch_charts.sh──▶ charts/*.html
                                               │
                                               ▼
                                         build_plif.py ──▶ genx-radio.plif ─┐
                                               ▲                           │
                                               │                           ▼
                          albums/albums.json ◀──────── lookup_albums.py ◀──── MusicBrainz API
```

1. **Download the charts.** `fetch_charts.sh` saves every weekly Top 50 singles
   chart page from musicchartsarchive.com as a local HTML file.
2. **Build the playlist.** `build_plif.py` parses those pages, takes positions
   1–40 from each week, removes duplicate songs, and writes `genx-radio.plif`.
3. **Fill in albums.** The chart site doesn't list albums, so
   `lookup_albums.py` reads the song list from `genx-radio.plif`, asks
   MusicBrainz which album each song first appeared on, and saves the answers
   to `albums/albums.json`. Running `build_plif.py` again copies those album
   names into the playlist.

Step 3 needs the song list from step 2, so the first time through you run
`build_plif.py` twice: once before the album lookup and once after.

## Quick start

```sh
./fetch_charts.sh            # download charts (skips files you already have)
./build_plif.py              # first build, without albums
./lookup_albums.py           # look up albums (slow: about 1 request per second)
./build_plif.py              # rebuild with albums
```

## Files

| Path | What it is |
|------|------------|
| `fetch_charts.sh` | Downloads chart pages. Saves each year's index page to `charts/index/YYYY.html`, finds that year's weekly chart dates in it, then downloads each week to `charts/YYYY-MM-DD.html`. Waits 1 second between requests and skips files already on disk, so you can safely re-run it. Usage: `./fetch_charts.sh [start-year] [end-year]` (default 1976–2005). |
| `charts/YYYY-MM-DD.html` | 1,535 saved weekly chart pages (1976-08-07 through 2005-12-31), so nothing needs to be downloaded again. |
| `charts/index/YYYY.html` | The yearly index pages that list each week's chart date. |
| `fetch.log` | Output from the chart download run (`<date> ok` per week, `FAIL` lines on errors). |
| `build_plif.py` | Turns the saved charts into the playlist (details below). |
| `genx-radio.plif` | **The output**: a Playlisty import file in JSON format, with one row per song (`name`, `artist`, `album`). |
| `lookup_albums.py` | Finds each song's original album on MusicBrainz (details below). |
| `albums/mb_cache.jsonl` | Cache of MusicBrainz results, one JSON line per song: the queries sent and the matching release groups that came back. Songs already in the cache are never looked up again. |
| `albums/albums.json` | The album chosen for each song, keyed by `"title\tartist"`. Each entry has the `album`, `date`, `source` (`musicbrainz` or `old-plif`), and for MusicBrainz matches the `release_group` ID and `kind` (for example `Album + Soundtrack`). |
| `albums/lookup.log` | Output from the album lookup runs. |

## `build_plif.py` in detail

```
build_plif.py [--top 40] [--start 1976] [--end 2005] [--min-points 0]
              [--caption "GenX Radio"] [--description "..."] [-o genx-radio.plif]
```

- **Parsing:** a regex reads the `position / title / artist` rows from each
  chart's table. HTML tags and entities are removed, and notes the site adds
  to titles, such as `[re-release]`, are dropped.
- **Order:** charts are processed oldest first, and within each week by chart
  position. A song's place in the playlist is therefore the week it first
  entered the Top 40, with higher positions first within that week.
- **Removing duplicates:** two entries count as the same song when the title
  and the *lead* artist match after lowercasing and removing punctuation. The
  lead artist is the name before `&`, `and`, `feat.`, `with`, `x`, `vs.`, or a
  comma, so "X" and "X ft. Y" with the same title count as one song. Only the
  first appearance is kept.
- **Typos:** `TITLE_TYPOS` / `ARTIST_TYPOS` list misspellings in the chart
  data (for example `Suvivor`). They're only used when matching, so a typo'd
  week counts toward the correctly spelled song, and the playlist shows the
  correct spelling.
- **Weighting (`--min-points N`):** each week a song spends on the chart earns
  `TOP + 1 - position` points (#1 = 40 … #40 = 1). Only songs totalling at
  least `N` points are kept, still in first-charted order. `--min-points 100`
  keeps 3,624 of 5,581 songs. Because the charts start on 1976-08-07 (the site
  has nothing earlier), songs already charting by then are scored only on
  their weeks from that date on; songs still charting at the end of 2005 are
  likewise cut short.
- **Albums:** looked up in `albums/albums.json` by the exact `title\tartist`
  key. Curly quotes, special dashes and `…` are converted to plain ASCII.
- Prints a warning if any chart had fewer rows than `--top`, which usually
  means a page didn't download completely.

## `lookup_albums.py` in detail

```
lookup_albums.py [--plif genx-radio.plif] [--fallback ~/genx-radio.plif] [--offline]
```

The goal is the **first album a song appeared on**: the artist's studio album,
or the movie soundtrack it came from. Later greatest-hits albums and
"Various Artists" compilations should lose.

**Searching** (`search()`):
- First corrects known typos and nicknames in the chart data (`ARTIST_FIXES`,
  `TITLE_FIXES`), for example `Suvivor` → `Survivor` and `ELO` →
  `Electric Light Orchestra`. Nicknames in quotes are removed, so
  `Missy "Misdemeanor" Elliott` becomes `Missy Elliott`.
- Tries several versions of the title: as written, without anything in
  brackets, with the brackets removed but the words kept, and each half of a
  double A-side (`A / B`).
- Sends queries from most to least specific: exact title + lead artist
  (official releases only), then looser searches, then the full artist credit.
  It stops as soon as it finds a usable album.
- `candidates()` keeps only results whose recording title and artist actually
  match, then groups them by release group and records the earliest release
  date of each.
- Requests are sent about 1 per second, following MusicBrainz's rate limit.
  On 5xx/429 errors or network failures it waits and retries.

**Ranking** (`pick_tier()` / `pick()`):

| Tier | Accepted |
|------|----------|
| 0 | Album by the artist (studio or compilation), or any soundtrack |
| 1 | EP by the artist |
| 2 | Live or remix album by the artist |
| — | Everything else: singles, Various Artists compilations, foreign telenovela / dubbed-film / TV-series "soundtracks" (`SOUNDTRACK_SKIP`), soundtracks with non-Latin titles |

The best tier wins. Within a tier, the earliest **year** wins. Many releases
only have a year, so ties within the same year go to: a soundtrack by someone
else, then the artist's studio album, then the artist's compilation, then the
exact date.

**Fallback:** if MusicBrainz finds nothing usable, the script takes the album
name from an older `.plif` (by default `~/genx-radio.plif`) when that song is
in it. In the last run: 5,500 from MusicBrainz, 23 from the fallback, and 64
with no album.

**Re-running:** results are added to the cache as they arrive, so you can stop
the script and start it again without losing work. Use `--offline` to re-pick
albums from the cache without contacting MusicBrainz, which is useful after
changing the ranking rules. To look up particular songs again, delete their
lines from `albums/mb_cache.jsonl`.
