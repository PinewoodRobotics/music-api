#!/usr/bin/env bash
# Rebuilds src/embed/sf-symbols.woff2 (the FMS touch panel's ?embed=fms icons) from SF-Pro.ttf, keeping only the
# symbols in src/embed/icons.ts. Find a code point with:
#   "/Applications/SF Symbols.app/Contents/Executables/sfsymbols" search --match-style exactName --show-codepoint <name>
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${SF_PRO_TTF:-$HOME/Developer/PWRUP-vibecoded-admin-panel/apps/comp/public/fonts/SF-Pro.ttf}"
unicodes=$(grep -oE '\\u\{[0-9A-F]+\}' "$DIR/src/embed/icons.ts" | sed -E 's/\\u\{([0-9A-F]+)\}/U+\1/' | sort -u | paste -sd, -)
uvx --from fonttools --with brotli pyftsubset "$SRC" --unicodes="$unicodes" --flavor=woff2 \
  --layout-features='*' --output-file="$DIR/src/embed/sf-symbols.woff2"
ls -l "$DIR/src/embed/sf-symbols.woff2"
