#!/usr/bin/env bash
# Builds the Flatpak from this checkout (packaging/flatpak, #148) into target/flatpak/:
#   MisterDownloadManager-<version>-linux-x86_64.flatpak   a bundle: flatpak install --user <file>
# and its repository (target/flatpak/repo), which flatpak-builder-lint checks. Nothing is
# published. Needs flatpak and flatpak-builder (1.4 or later), and what cargo-sources.sh needs;
# the runtime, its SDK and the Rust extension come from Flathub (a user remote, added if missing).
#   tools/flatpak/build.sh [--install]      --install: also installs it for this user
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
id=com.misterdownloadmanager.MisterDownloadManager
manifest="$root/packaging/flatpak/$id.yml"
out="$root/target/flatpak"
version="$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' "$root/Cargo.toml" | head -1)"
mkdir -p "$out"

flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
bash "$root/tools/flatpak/cargo-sources.sh"

install=()
[ "${1:-}" = "--install" ] && install=(--install)
flatpak-builder --user --install-deps-from=flathub --force-clean --disable-rofiles-fuse \
  --state-dir="$out/state" --repo="$out/repo" "${install[@]}" "$out/build" "$manifest"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$out/repo" "$out/MisterDownloadManager-$version-linux-x86_64.flatpak" "$id"
ls -l "$out"/*.flatpak
