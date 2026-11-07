# Packages for package managers

MDM in WinGet, the AUR and the Microsoft Store. Prepared, checked, and **not submitted
anywhere yet**: they go in after 0.3.0 ships, by the maintainer.

| Folder | What | Checked with |
| --- | --- | --- |
| [`winget/`](winget/) | WinGet manifests for the current release, in winget-pkgs' layout | `winget validate` (also on every pull request that changes them) |
| [`aur/`](aur/) | The AUR package `misterdownloadmanager-bin`, and `update.sh` to move it to a release | built with `makepkg`, `namcap`, installed and run on Arch (also built on every pull request that changes it) |
| [`msstore/`](msstore/) | What the Microsoft Store needs, and the listing's texts | [`msstore/README.md`](msstore/README.md) |

After the first submission by hand, each release can go to WinGet and the AUR by itself:
[`.github/workflows/package-managers.yml`](../.github/workflows/package-managers.yml), started by
`release.yml` once a release is published. It's **off** until turned on (below).

## WinGet

- **Identifier: `AhmedNefzaoui.MisterDownloadManager`**, as winget-pkgs names packages
  (publisher, then name; the publisher is the installer's, `AppPublisher` in
  [`mdm.iss`](../tools/installer/mdm.iss)). Nothing in winget-pkgs uses it or the name yet
  (checked 2026-11-07). Users type `winget install AhmedNefzaoui.MisterDownloadManager`, or
  `winget install "Mister Download Manager"`, or `winget install misterdownloadmanager` (the
  moniker).
- **One installer, both scopes.** The Inno Setup installer installs for one user (no
  administrator, `%LOCALAPPDATA%\Programs`) or for everyone (Program Files): `/CURRENTUSER` and
  `/ALLUSERS` choose without the wizard's question, and winget adds its own silent switches for
  Inno (`/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`). `winget install` takes the user scope;
  `--scope machine` the other.
- **Upgrades** find the installed copy by the installer's `AppId`: its uninstall entry is
  `{667DB4D8-32C2-4487-A0E5-5825BF29778C}_is1` (`ProductCode`, `AppsAndFeaturesEntries`), as Komac
  also reads it from the installer. MDM updating itself keeps working: winget sees the new version
  in Apps and Features.
- **A silent install takes the installer's default tasks**: browser integration, `.torrent`
  files and magnet links, and start with Windows (the wizard's defaults).
- **The Visual C++ runtime**: MDM's programs need `VCRUNTIME140.dll`, which the installer doesn't
  bring (Windows doesn't always have it), so the manifest depends on
  `Microsoft.VCRedist.2015+.x64`.
- **No portable package.** WinGet's portable packages live in a folder winget owns and deletes on
  uninstall and upgrade: the portable zip's `data` folder (the download list and settings) would
  go with it, and neither zip sets up browser integration. The installer covers both scopes.

### The first version, by hand

The first version of a package goes in by hand; Komac keeps it up to date from then on.

1. Update the manifests to the release (or let Komac write them:
   `komac new AhmedNefzaoui.MisterDownloadManager` from the installer's URL, then compare with
   these).
2. `winget validate --manifest packaging/winget/manifests/a/AhmedNefzaoui/MisterDownloadManager/<version>`.
3. Optional, in Windows Sandbox or a virtual machine (not a computer with MDM installed):
   `winget install --manifest <that folder>`, then `winget uninstall
   AhmedNefzaoui.MisterDownloadManager`.
4. Submit: `komac submit <that folder>` (or `wingetcreate submit <that folder>`), with a GitHub
   token (below). It forks `microsoft/winget-pkgs` to your account and opens the pull request.
   A Microsoft reviewer and their checks (installer scan, a test install) follow; then
   `winget install` finds it.

### Each release after that

`package-managers.yml`'s `winget` job runs [Komac](https://github.com/russellbanks/Komac)
(pinned version and checksum): `komac update AhmedNefzaoui.MisterDownloadManager --version
<version> --urls <the release's setup.exe> --submit`. Komac takes the previous version's
manifests from winget-pkgs, puts the new installer in (hash, both scopes, ProductCode, release
date and notes) and opens the pull request from the token's fork.

To turn it on, in the repository's **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `WINGET_SUBMIT` | `true` |
| Secret | `WINGET_TOKEN` | A **classic** personal access token with the **`public_repo`** scope only, of the GitHub account that opens the pull requests (Komac makes its fork of winget-pkgs). Fine-grained tokens can't open pull requests on winget-pkgs yet. Give it an expiry and renew it. |

A dry run (Actions → Package managers → Run workflow, with the tag and **Dry run**) writes the
manifests without opening a pull request.

## AUR

- **`misterdownloadmanager-bin`**: the release's `.deb`, unpacked, so the same programs, desktop
  entry, icon and browser extension as the `.deb` and `.rpm`; nothing is compiled. The `.deb`
  rather than the `.tar.gz`, because the `.tar.gz` has no desktop entry or icon.
- **Dependencies**: the programs link only `glibc` and `libgcc`; the window opens the rest at run
  time (OpenGL through `libglvnd`, Wayland, X11, `libxkbcommon`, D-Bus for the tray and the theme),
  read from the programs' own library names. `namcap` can't see run-time loading, so it says those
  "may not be needed": they are. No GTK: the `.deb`'s `libgtk-3-0` is more than MDM needs. The
  optional ones: the portal or zenity for file pickers, `xdg-utils`, a Secret Service keyring,
  Vulkan, and the system's `yt-dlp` and `ffmpeg`.
- **Browser integration** works as from the `.deb`: MDM registers its native messaging host for
  the browsers it finds, in the user's home folder, at every start. The package writes nothing for
  everyone; on removal it says where the per-user files are.
- **To fix before it's listed: MDM's own Update now.** MDM tells how it was installed from where
  its program is (`crates/tools/src/update.rs`, `Install::detect`): in `/usr/bin` without
  `/etc/debian_version`, it takes itself for the `.rpm`, so on Arch **Update now** would fetch the
  `.rpm` and open it, and a bug report would say "The .rpm". A copy pacman installed should leave
  updates to pacman (say "update it with your package manager") and say "The AUR".
- **Not done: a source package `misterdownloadmanager`** (built with cargo). A clean build of the
  whole workspace takes long and needs PowerShell for the browser extension (`pack.ps1`, AUR
  only), for the same programs the `-bin` package already gives. Worth it if Arch users ask for
  one.

Checked on Arch (2026-11-07, a chroot from Arch's bootstrap image in a WSL machine): `makepkg`
builds it from the 0.2.4 release, `namcap` has nothing to say about the PKGBUILD, the package
installs, `desktop-file-validate` passes, `misterdownloadmanager-cli get` downloads a 48 MB file
from the lab server with the right checksum, the window opens (Xvfb, Mesa), the host registers for
Firefox and Chromium and unregisters, and the package removes cleanly. `namcap`'s other warnings
on the package are the run-time libraries above, `ld-linux` "unused" (it's the loader), and
0.2.4's symbol tables (build-linux.sh strips them fully since).

### The first version, by hand

1. An account on [aur.archlinux.org](https://aur.archlinux.org/register) with an SSH public key
   (My Account → SSH Public Key). A key for the AUR only: `ssh-keygen -t ed25519 -f ~/.ssh/aur`.
2. On Arch: `packaging/aur/update.sh <version>` (the PKGBUILD's version, checksum and `.SRCINFO`
   for that release), then in `packaging/aur/misterdownloadmanager-bin`: `makepkg -si` and
   `namcap PKGBUILD *.pkg.tar.zst`.
3. `git clone ssh://aur@aur.archlinux.org/misterdownloadmanager-bin.git`, copy `PKGBUILD`,
   `.SRCINFO` and `misterdownloadmanager-bin.install` in, commit, `git push`. That creates the
   package.

### Each release after that

`package-managers.yml`'s `aur` job, in an Arch container: `update.sh <version>`, `makepkg` and
`namcap`, then the three files pushed to the AUR's git (its host key checked against the one
aur.archlinux.org publishes). The committed copy here is the template; the AUR holds each
release's.

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `AUR_SUBMIT` | `true` |
| Secret | `AUR_SSH_PRIVATE_KEY` | The **private** key of that AUR account (the whole `~/.ssh/aur` file). No passphrase, so use a key made for the AUR alone. |
| Variable (optional) | `AUR_EMAIL` | The e-mail address on the AUR commits (else the GitHub no-reply one). |

A dry run builds and checks the package without pushing (no secret needed).

## Turning it off

Delete the variable (or set it to anything but `true`). Nothing else runs then: the release
starts the workflow only when one of them is `true`, and each job checks its own.
