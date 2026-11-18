#!/bin/zsh
# Download weekly Top 50 singles charts from musicchartsarchive.com into ./charts
# Chart dates come from each year's index page (saved in ./charts/index/YYYY.html).
# Already-downloaded files are skipped, so it's safe to re-run.
# Usage: ./fetch_charts.sh [start-year] [end-year]
cd "${0:A:h}"
mkdir -p charts/index
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
get() { # url outfile
  local code
  code=$(curl -sL -A "$UA" -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
    -H "Accept-Language: en-US,en;q=0.9" -o "$2.tmp" -w "%{http_code}" "$1")
  if [[ "$code" == 200 ]]; then mv "$2.tmp" "$2"; return 0; fi
  rm -f "$2.tmp"; echo "FAIL $code $1"; return 1
}
for y in $(seq ${1:-1976} ${2:-2005}); do
  idx="charts/index/$y.html"
  [[ -s "$idx" ]] || { get "https://musicchartsarchive.com/singles-charts/$y" "$idx"; sleep 1; }
  for d in $(grep -o "singles-chart/$y-[0-9][0-9]-[0-9][0-9]" "$idx" | sed 's|.*/||' | sort -u); do
    out="charts/$d.html"
    [[ -s "$out" ]] && continue
    get "https://musicchartsarchive.com/singles-chart/$d" "$out" && echo "$d ok"
    sleep 1
  done
done
echo DONE
