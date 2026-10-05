#!/usr/bin/env bash
# make basemap: the admin map's basemap, served from our own server (decisions.md A31). Writes
# var/basemap/ (kept out of git):
#   oqj.pmtiles      a Protomaps basemap extract (OpenStreetMap data) for the area below
#   fonts/           the map's label fonts as glyph ranges (Noto Sans, SIL Open Font Licence)
#   sprites/v4/      the style's icons (light)
#   VERSION          what was fetched, and when
# Caddy serves the folder at /basemap/* behind the site's basic auth, with HTTP range requests
# (the map reads tiles out of the one .pmtiles file by range); a dev server serves it too
# (web/vite.config.ts). Nothing on the map is fetched from anywhere else at runtime.
#
# This script is the only thing that reaches outside: the extract is cut from Protomaps' daily
# planet build with go-pmtiles (in Docker, nothing installed), fetching only the tiles inside
# the box; the fonts and sprites come from protomaps/basemaps-assets at a pinned commit.
#   make basemap                          the latest daily build
#   BASEMAP_BUILD=20261003 make basemap   a given day's build (they're kept for a few weeks)
set -euo pipefail
cd "$(dirname "$0")/.."

# High Wycombe, Marlow, Beaconsfield and Princes Risborough, with a margin: at least longitude
# -0.95 to -0.55 and latitude 51.52 to 51.76 (A31).
BBOX="${BASEMAP_BBOX:--0.97,51.50,-0.53,51.78}"
MAXZOOM="${BASEMAP_MAXZOOM:-15}"
BUILD="${BASEMAP_BUILD:-latest}"
PMTILES_IMAGE="protomaps/go-pmtiles:v1.31.2"
ASSETS_COMMIT="028c18f713baecad011301ff7a69acc39bcc2ae7"  # protomaps/basemaps-assets, 31 Oct 2025
# Every fontstack the style names (web/src/admin/map.test.tsx checks they match).
FONTS=("Noto Sans Regular" "Noto Sans Medium" "Noto Sans Italic" "Noto Sans Devanagari Regular v1")
SPRITE="light"
OUT="var/basemap"

mkdir -p "$OUT"
work="$(mktemp -d "$OUT/.build.XXXXXX")"
trap 'rm -rf "$work"' EXIT

if [ "$BUILD" = latest ]; then
  BUILD="$(curl -fsS https://build-metadata.protomaps.dev/builds.json |
    python3 -c 'import json, sys; print(json.load(sys.stdin)[-1]["key"].removesuffix(".pmtiles"))')"
fi
[[ "$BUILD" =~ ^[0-9]{8}$ ]] || { echo "BASEMAP_BUILD must be a date like 20261003 (got $BUILD)" >&2; exit 1; }

echo "== Basemap extract: Protomaps build $BUILD, bbox $BBOX, zoom 0 to $MAXZOOM"
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/$work:/out" "$PMTILES_IMAGE" \
  extract "https://build.protomaps.com/$BUILD.pmtiles" /out/oqj.pmtiles \
  --bbox="$BBOX" --maxzoom="$MAXZOOM" --download-threads=4 2>&1 | grep -v "fetching chunks" || true
[ -s "$work/oqj.pmtiles" ] || { echo "The extract failed (no file written)" >&2; exit 1; }
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/$work:/out" "$PMTILES_IMAGE" verify /out/oqj.pmtiles

echo "== Fonts and sprites: protomaps/basemaps-assets@${ASSETS_COMMIT:0:7}"
curl -fsSL "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/$ASSETS_COMMIT" -o "$work/assets.tgz"
top="basemaps-assets-$ASSETS_COMMIT"
members=("$top/fonts/OFL.txt")
for f in "${FONTS[@]}"; do members+=("$top/fonts/$f"); done
for s in "$SPRITE.json" "$SPRITE.png" "$SPRITE@2x.json" "$SPRITE@2x.png"; do members+=("$top/sprites/v4/$s"); done
tar -xzf "$work/assets.tgz" -C "$work" "${members[@]}"
for f in "${FONTS[@]}"; do
  [ -s "$work/$top/fonts/$f/0-255.pbf" ] || { echo "Missing glyphs for $f" >&2; exit 1; }
done

cat > "$work/VERSION" <<EOF
Protomaps basemap build $BUILD (https://build.protomaps.com/$BUILD.pmtiles), bbox $BBOX, max zoom $MAXZOOM
Map data © OpenStreetMap contributors (ODbL). Tiles: Protomaps basemap.
Fonts and sprites: protomaps/basemaps-assets@$ASSETS_COMMIT (fonts: SIL Open Font Licence, fonts/OFL.txt)
Fetched $(date -u +%Y-%m-%dT%H:%M:%SZ) by make basemap
EOF

# Into place: the fonts and sprites first, the extract last and by rename, so whoever is reading
# the old file is never handed a half-written one.
rm -rf "$OUT/fonts" "$OUT/sprites"
mkdir -p "$OUT/sprites"
mv "$work/$top/fonts" "$OUT/fonts"
mv "$work/$top/sprites/v4" "$OUT/sprites/v4"
mv "$work/VERSION" "$OUT/VERSION"
mv "$work/oqj.pmtiles" "$OUT/oqj.pmtiles"
chmod -R a+rX "$OUT"
echo "== Done: $(du -sh "$OUT" | cut -f1) in $OUT"
cat "$OUT/VERSION"
