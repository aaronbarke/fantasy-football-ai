#!/bin/sh
# Bundle the extension into the zip the Connect page offers for download
# (frontend/public/ffai-espn-connect.zip). Run after changing anything here.
set -eu
cd "$(dirname "$0")"
out="../frontend/public/ffai-espn-connect.zip"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/ffai-espn-connect/icons"
cp manifest.json background.js content.js popup.html popup.js "$stage/ffai-espn-connect/"
cp icons/*.png "$stage/ffai-espn-connect/icons/"
rm -f "$out"
(cd "$stage" && zip -qr -X "$OLDPWD/$out" ffai-espn-connect)
echo "Wrote $out"
