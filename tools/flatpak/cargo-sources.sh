#!/usr/bin/env bash
# packaging/flatpak/cargo-sources.json from Cargo.lock: every crate (and the git ones: the egui,
# winit and rqbit forks, craft-libs, by their pinned commits) as a source flatpak-builder fetches
# before the build, which runs offline. Made by flatpak-builder-tools' flatpak-cargo-generator,
# at a pinned commit. Run it again after Cargo.lock changes (build.sh does).
# Needs python3 with aiohttp, PyYAML and tomlkit (Ubuntu: python3-aiohttp python3-yaml
# python3-tomlkit), and curl.
#   tools/flatpak/cargo-sources.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
rev=41c20aa10819cdb2a4f3ca171758a96d1955c018
gen="$root/target/flatpak/flatpak-cargo-generator-$rev.py"
if [ ! -f "$gen" ]; then
  mkdir -p "$(dirname "$gen")"
  curl -fsSL -o "$gen.part" \
    "https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/$rev/cargo/flatpak-cargo-generator.py"
  mv "$gen.part" "$gen"
fi
python3 "$gen" "$root/Cargo.lock" -o "$root/packaging/flatpak/cargo-sources.json"
