# The Flatpak

Mister Download Manager as a Flatpak (#148):

| File | What it is |
|---|---|
| `com.misterdownloadmanager.MisterDownloadManager.yml` | The manifest: the runtime, the sandbox's permissions (each with its reason), the build from source |
| `com.misterdownloadmanager.MisterDownloadManager.metainfo.xml` | AppStream: what software centres show (a test keeps its releases equal to CHANGELOG.md's) |
| `com.misterdownloadmanager.MisterDownloadManager.desktop` | The menu entry, which also offers MDM for magnet links and `.torrent` files |
| `icons/` | The app's icon (`art/`) at 64, 128, 256 and 512 pixels |
| `screenshots/` | The metainfo's screenshots, taken from the Flatpak itself |
| `cargo-sources.json` | Not kept in git: every crate of `Cargo.lock`, made by `tools/flatpak/cargo-sources.sh` |

Build it with `tools/flatpak/build.sh` (`--install` installs it for you): the bundle lands in
`target/flatpak/`. The Flatpak workflow builds the same on GitHub for every change to these files
and keeps the bundle as the run's artifact.

What changes inside the sandbox, for the person using it, is in
[docs/getting-started.md](../../docs/getting-started.md#flatpak); the code that asks whether it
runs in one is `mdm_ipc::flatpak` and `crate::unix::in_flatpak`.
