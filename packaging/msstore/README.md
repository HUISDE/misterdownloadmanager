# Microsoft Store

The Microsoft Store takes ordinary Windows installers (`.exe` or `.msi`) through Partner Center:
the Store shows the listing, and installs MDM by downloading the release's `setup.exe` from
GitHub and running it silently. MDM's own updates keep working (the Store's rule that a product
updates only through the Store is for games and MSIX packages, not installers: policy 10.2.5).

Prepared 2026-11-07, **nothing submitted**. One requirement isn't met yet: **the installer must be
code-signed** (below).

## What the maintainer does

1. **A developer account, free.** Since September 2025 individual developers register for free
   (the $19 fee is gone; companies still pay $99). Start at
   **[storedeveloper.microsoft.com](https://storedeveloper.microsoft.com)** → *Get started for
   free* → *Individual developer*; other entry points still show the old paid flow. You sign in
   with a Microsoft account and verify your identity with a government ID and a selfie, then land
   in Partner Center. Sources: [Free developer registration for individual
   developers](https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer)
   (Microsoft Learn), [the announcement](https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/)
   (Windows Developer Blog, 2025-09-10). An individual account fits: the publisher shown is
   your name, as in the installer (policy 10.14 asks for a company account only when the name
   reads as a business).
2. **Reserve the name**: Partner Center → *Apps and games* → *New product* → *EXE or MSI app* →
   **Mister Download Manager**.
3. **Code-sign the installer** (the one thing missing, below), and release 0.3.0 signed.
4. **Packages**: the installer's URL for that version and its switches (below), architecture
   x64, language English (the installer has every interface language).
5. **Store listing** (English, from this file): description, *What's new*, features, keywords,
   screenshots, logo, the links.
6. **Properties**: category *Utilities & tools*; privacy policy
   `https://misterdownloadmanager.com/privacy.html`; website `https://misterdownloadmanager.com/`;
   support `https://github.com/anefzaoui/misterdownloadmanager/issues`; system requirements
   Windows 10 or 11, x64.
7. **Age rating**: the IARC questionnaire, answered as it is: no violence, no mature content, no
   purchases, no ads, no user accounts or chat; it **downloads files from the internet** that the
   user chooses (say yes where it asks about unrestricted internet access or downloading content).
8. **Pricing and availability**: free, every market.
9. **Submission options → Notes for certification** (draft below), then submit. Certification
   takes up to a few business days.
10. **Each release**: a new submission with the new version's URL (the Store doesn't follow
    GitHub releases by itself). It can be automated later with Partner Center's submission API
    (`msstore` CLI), which needs an Azure AD app registration; not set up here.

## What the installer must meet (policy 10.2.9)

From [Microsoft Store Policies 10.2.9](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)
(version 7.20, 2026-09-14) and [App package requirements for MSI/EXE
apps](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/app-package-requirements):

| Requirement | MDM today |
| --- | --- |
| An `.exe` or `.msi` | ✅ `MisterDownloadManager-<version>-setup.exe` (Inno Setup) |
| **The installer and every program file (PE) in it signed** with a certificate that chains to a CA in the Microsoft Trusted Root Program | ❌ **Not signed.** 0.2.4's `setup.exe` has no signature (`Get-AuthenticodeSignature`: NotSigned), and the repository has no signing secrets. `release.yml` and `build.ps1` are ready for a certificate: with one, Inno Setup signs the four programs, the installer and its uninstaller. |
| A versioned HTTPS download URL whose file never changes | ✅ `https://github.com/anefzaoui/misterdownloadmanager/releases/download/v<version>/MisterDownloadManager-<version>-setup.exe`. Never replace a release's asset after submitting it (`gh release upload --clobber`): the Store checks the file it certified. |
| Installs without showing a window (UAC allowed) | ✅ with the switches given in Partner Center: **`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`**. Silent, it installs for the current user (no UAC), with the default tasks (browser integration, `.torrent` files and magnet links, start with Windows), and doesn't start MDM at the end. |
| A standalone installer, not a downloader | ✅ everything is in `setup.exe`. |
| PC only | ✅ |

Two more things certification is likely to look at:

- **The Visual C++ runtime.** The programs need `VCRUNTIME140.dll` (the Visual C++
  Redistributable), which the installer doesn't install and a clean Windows doesn't always have;
  certification installs on a clean machine. Fix before submitting: build the Windows programs
  with the C runtime linked in (`-C target-feature=+crt-static` for
  `x86_64-pc-windows-msvc`), or have the installer bring the runtime.
- **Programs MDM downloads later.** Video downloads use yt-dlp and ffmpeg, which MDM downloads
  from their official releases the first time a video needs them (policy 10.2.2 on code that
  arrives later, 10.2.4 on dependencies). Say so at the start of the description and in the notes
  for certification (both drafted below).

### Signing: the options

Code-signing certificates are no longer handed out as a file: since June 2023 the CA/Browser
Forum's rules keep the private key in hardware (a token or a cloud service). So the `.pfx` that
`release.yml`'s `CODESIGN_PFX_BASE64` secret expects only fits a certificate exported before that;
a new one signs through its service's tool, and that step of `release.yml` changes with it
(`build.ps1` takes any signing command in `MDM_SIGN_COMMAND`, so only the command changes).

| Option | Cost | Notes |
| --- | --- | --- |
| [SignPath Foundation](https://signpath.org/) (free for open source) | Free | For OSI-licensed projects built in public CI; the certificate is SignPath Foundation's, so Windows shows **SignPath Foundation** as the publisher, and their terms ask for MFA on the repository and a published signing policy. Signs from GitHub Actions. |
| [Azure Artifact Signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) (was Trusted Signing) | Monthly fee | Your name as publisher. Individuals: only in the USA and Canada for now (organizations: also the EU and UK). Signs from GitHub Actions. |
| An OV certificate from a CA (with a token or the CA's cloud signing) | Roughly $150-300 a year | Your name as publisher; renewed every year or so. |
| MSIX instead of the installer | Free (the Store signs it) | A different package: Store-only updates (MDM's own updater off), and browser integration's registry entries need work in MSIX. Not worth it while the installer route is open. |

A signed installer also ends the "Windows protected your PC" warning on the download page as the
signature earns reputation.

## Store listing (draft)

Plain words, nothing about other products. Up to 10,000 characters for the description, 200 per
feature, 7 keywords.

**Name**: Mister Download Manager

**Short description** (shown first):

> A free, open-source download manager: faster downloads with several connections at once,
> resume after any interruption, and downloads caught from your browser.

**Description**:

> Mister Download Manager downloads your files faster by fetching several parts of each file at
> the same time, and keeps every connection busy until the last byte. If the connection drops,
> the computer restarts or a download is paused, it resumes where it stopped instead of starting
> over.
>
> With its browser extension for Firefox, Chrome, Edge, Brave, Opera and Vivaldi, the downloads
> you start in the browser come to Mister Download Manager by themselves, and a button over
> videos on web pages downloads them. It downloads torrents and magnet links too.
>
> Organise downloads in categories, run them in queues, and let the scheduler start them at night
> and shut the computer down when they're done. Limit the speed so the rest of your network stays
> fast. Everything is in 86 languages, in light and dark mode, and works from the keyboard and
> with screen readers.
>
> Free and open source (GPL-3.0): no ads, no trial, no account. It collects nothing about you.
>
> Video downloads use yt-dlp and ffmpeg, free programs that Mister Download Manager downloads
> from their official releases the first time you download a video. Browser integration needs
> the Mister Download Manager extension from the Chrome Web Store or Firefox Add-ons.

**Features** (one per line in Partner Center):

- Several connections per file, re-balanced until the download ends
- Resumes after a crash, a restart or a dropped connection
- Catches downloads from Firefox, Chrome, Edge, Brave, Opera and Vivaldi
- Downloads videos from web pages with one click
- Torrents and magnet links, with file selection and seeding limits
- Queues and a scheduler that can start downloads at night and shut the computer down
- Speed limits for one download or all of them
- 86 languages, right to left for Arabic, Hebrew, Persian, Urdu and Uyghur
- Light and dark mode
- Keyboard and screen reader support (Narrator, NVDA)
- Command-line tool and a local API for scripts
- No ads, no trial, no account; open source

**Keywords** (7): download manager, downloader, download accelerator, resume downloads, torrent,
video downloader, magnet

**What's new** (per release): the release's section of `CHANGELOG.md`, shortened.

**Copyright**: Copyright (C) 2026 Ahmed Nefzaoui

**Screenshots**: 1 required, 4 or more recommended, up to 10: the main window (light and dark),
Add URL, the progress window, a torrent, the video button in a browser, the scheduler, the
language picker. Take them new at full size from a running MDM (the ones in `docs/images` are
930 × 500 and smaller); a neutral download list, no other products' artwork.

**Logo**: the 1:1 box art (required) and the 2:3 poster (recommended), from
`art/Mister Download Manager.png` (1254 × 1254), at the sizes Partner Center asks.

**Notes for certification** (draft):

> Mister Download Manager is a download manager. The installer runs silently with
> /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- and installs for the current user without
> administrator rights. To test: start Mister Download Manager, choose a language, then Tasks →
> Add new download, paste
> https://github.com/anefzaoui/misterdownloadmanager/releases/download/v0.2.4/MisterDownloadManager-0.2.4-portable.zip
> (or any large file) and click OK.
> Video downloads use yt-dlp and ffmpeg (free software), which the app downloads from their
> official GitHub releases the first time a video is downloaded, and checks against their
> published checksums (yt-dlp's signed by its publisher) before use. Browser
> integration needs the app's extension from the Chrome Web Store or Firefox Add-ons; the app
> works without it. The app updates itself from GitHub releases, signed by its release key. No
> account is needed; the app collects no data (privacy policy linked).
