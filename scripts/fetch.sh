#!/bin/bash
D=${1:-./ripperdeck_dl}
grep -oE 'href="/cards/[a-z0-9-]+"' $D/rd.html | sed -E 's#href="/cards/([^"]+)"#\1#' | sort -u > $D/slugs.txt
while read s; do
  f=$D/pages/$s.html
  [ -s "$f" ] && continue
  curl -sS --retry 3 -A "cptcg-sim-research/0.1 (personal deck-testing project)" -o "$f" "https://ripperdeck.gg/cards/$s" || echo "FAIL $s"
  sleep 2
done < $D/slugs.txt
echo done $(ls $D/pages | wc -l)
