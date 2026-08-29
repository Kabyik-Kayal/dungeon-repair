#!/usr/bin/env bash
# Fetch the Video Game Level Corpus (MIT licensed) into data/TheVGLC.
# Pinned to a commit so the evaluation set is stable across machines.
set -euo pipefail

REPO="https://github.com/TheVGLC/TheVGLC.git"
COMMIT="${VGLC_COMMIT:-}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/TheVGLC"

if [ -d "$DEST/.git" ]; then
  echo "already present: $DEST"
else
  echo "cloning $REPO -> $DEST"
  git clone --quiet "$REPO" "$DEST"
fi

if [ -n "$COMMIT" ]; then
  git -C "$DEST" checkout --quiet "$COMMIT"
fi

echo "pinned commit: $(git -C "$DEST" rev-parse HEAD)"
for game in "The Legend of Zelda" \
            "The Legend of Zelda - Link to the Past" \
            "The Legend of Zelda - Link's Awakening"; do
  count=$(find "$DEST/$game/Graph Processed" -name '*.dot' | wc -l | tr -d ' ')
  echo "  $game: $count dungeon graphs"
done
