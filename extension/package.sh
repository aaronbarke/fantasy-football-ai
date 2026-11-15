#!/bin/sh
# Bundle the extension into frontend/public/ffai-espn-connect.zip: the file the
# Connect page offers for download, and the one to upload to the Chrome Web
# Store. Run after changing anything here.
#
# The packaged copy differs from this folder in one way: it only runs on the
# live site. The localhost entries in manifest.json are for development (load
# this folder unpacked), and would otherwise show up in the store's install
# warning as sites the extension can read.
set -eu
cd "$(dirname "$0")"
out="../frontend/public/ffai-espn-connect.zip"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/icons"
cp background.js content.js popup.html popup.js "$stage/"
cp icons/*.png "$stage/icons/"
python3 - "$stage/manifest.json" <<'PY'
import json
import sys

with open("manifest.json") as f:
    manifest = json.load(f)
for script in manifest["content_scripts"]:
    script["matches"] = [m for m in script["matches"] if m.startswith("https://")]
    if not script["matches"]:
        sys.exit("manifest.json: a content script has no https:// site to run on")
with open(sys.argv[1], "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY
rm -f "$out"
# manifest.json sits at the top of the zip, where the Chrome Web Store looks
# for it. Unzipping still gives a folder named after the file.
(cd "$stage" && zip -qr -X "$OLDPWD/$out" .)
echo "Wrote $out"
