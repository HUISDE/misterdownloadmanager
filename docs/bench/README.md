# Benchmarks

Two benchmarks live here. Both run on one Windows PC against the lab server from this
repository (`crates/labserver`) on 127.0.0.1, so no internet traffic is involved, and both
publish every run along with the statistics.

| Folder | What | Harness |
|---|---|---|
| [`run5/`](run5/REPORT.md) | IDM 6.42 against MDM, 7 scenarios, 2026-10-29 | `tools/bench/bench.py`, `report.py` |
| [`compare-2026-11/`](compare-2026-11/REPORT.md) | MDM against other download managers, 6 scenarios | `tools/bench/compare.py`, `compare_report.py` |

The rest of this page describes the comparison with the other download managers
([#71](https://github.com/anefzaoui/misterdownloadmanager/issues/71)).

<!--RESULTS-->

## What was compared

| App | Version | How the benchmark hands it a download | How it says a download is done | Its default connections |
|---|---|---|---|---|
| Mister Download Manager | this repository's commit (see `environment.json`) | its command line, `/d URL /p folder /f name /n`, to the running app | renames `name.mdm.part` to `name` | 8 |
| AB Download Manager | 1.11.4 (portable zip) | its documented local API, `POST /start-headless-download` on 127.0.0.1:15151 (`REST-API.yml` in its repository) | its download list (`~/.abdm/config/download_db/downloadlist/*.json`) says `Completed` | 8 |
| Free Download Manager | 6.35.2.7075 | its browser bridge (`wenativehost.exe`, the native-messaging host its extension talks to), with its "silent mode for new downloads" setting on so no dialog asks | its database (`db.sqlite`) gives the download a finish time | 15 per server (see below) |
| Gopeed | 1.9.3 (portable zip) | its browser bridge (`host.exe`), which forwards to its documented REST API (`POST /api/v1/tasks`) | its API says the task is `done` (asked every 50 ms) | 16 |
| Prism | 1.2.4 (portable zip) | its browser bridge (`prism-native-host.exe`), the `download` message its extension sends | renames `name.prismpart` to `name` | 8 |
| Xtreme Download Manager | 9.0.9 (MSI, unpacked with `msiexec /a`) | its documented command line, `xdm-app --headless -o folder [-f name] -s N URL...` | the command exits with 0 | 8 |
| aria2 | 1.37.0 | `aria2c` (one URL, or `-i list` for several) | the command exits with 0 | 1 (`-x1`) |
| curl | the copy in Windows (`C:\Windows\System32\curl.exe`) | `curl -sS --fail -o file URL ...` | the command exits with 0 | 1 (no segmenting) |
| Internet Download Manager | 6.42 build 25 | not run again: its numbers are run5's (2026-10-29, same PC, same lab server, same scenarios) | — | 8 |

Each GUI app was set to save into the benchmark's folder, with no "download complete" window,
no sounds or notifications, no update checks, no autostart and no clipboard watching, through
its own settings file. Nothing else was changed. Every GUI app ran with its main window open
(on the hidden desktop, below).

Free Download Manager keeps its connections per server in the preset of its traffic mode
("High": 15 per server) and restores that preset on every start; only its Options window
changes it. It therefore ran at its own 15 in every scenario, where the others had 8: the
tables say so on its row.

Motrix and Persepolis were left out: both drive aria2, which is here on its own. wget2 has no
official Windows build. IDM was left as the user had it: no download was handed to it again.

## Scenarios

| Id | What the server does | Size |
|---|---|---|
| `fast-1g` | nothing: as fast as the loopback and the disk allow | 1 GiB |
| `capped-100m` | at most 2 MB/s on each connection (a server that limits each connection) | 100 MiB |
| `drops-50m` | 4 MB/s per connection, and every second connection is cut after 2 MiB | 50 MiB |
| `maxconns-50m` | at most 2 connections at a time from one address (more get `503`), 2 MB/s each | 50 MiB |
| `norange-100m` | ignores `Range` and always sends the whole file (`200`) | 100 MiB |
| `batch-32x256k` | 32 different files, handed over one after another | 32 × 256 KiB |

The first four are run5's, so IDM's numbers from then can stand beside them.

Every app ran each scenario twice over:

- **8 connections each** ("matched"): every app that has the setting was set to 8
  connections per download.
- **Its defaults**: the 1 GiB and 2 MB/s scenarios again, for the apps whose default isn't 8
  and can be set (Gopeed, aria2). FDM and curl ran once: their connections can't be set here.

## How it was measured

- **The machine.** One Windows 11 PC (see `environment.json`). Every app saved to the same
  folder on drive C:.
- **No screen, no input.** The GUI apps ran on a separate Windows desktop that is never shown,
  so none of them could take the screen or the keyboard. Each was driven only through the way
  in it offers a browser extension or a script, as in the table above. No mouse or keyboard
  input was sent to any of them.
- **Time.** From the moment the hand-off starts (the command, the API call, the bridge
  message) until the app itself says the last file is complete, on a monotonic clock. The
  harness polls every 5 ms, Gopeed every 50 ms.
- **Correctness.** The SHA-256 of every downloaded file is checked against the lab server's
  generator (`tools/bench/content.py`, the same function as `crates/labserver/src/content.rs`).
  A file that is complete by its app's account but wrong counts as a failed run.
- **CPU.**
  - What it counts: the CPU time of the app's processes during the run, plus the hand-off
    helper (the native-messaging host a browser would start, or MDM's second command-line
    process).
  - Average: CPU seconds divided by the run's wall time, in cores (1.00 means one core busy
    the whole time).
  - Peak: the busiest 100 ms, in cores.
- **Memory.**
  - Peak: the highest total working set of those processes during the run.
  - Idle after: for the apps that stay running, their working set 3 s after the run.
  - The command-line tools exit, so they have no idle figure.
- **Connections and requests** come from the lab server's own log (`server.jsonl`).
- **Order and load.**
  - The apps run one at a time, in a new random order every round (seeded, so it can be
    repeated). Any load from other programs therefore falls on all of them alike.
  - The CPU used by everything else on the machine is recorded for every run, and so are any
    requests the lab server answered for other programs meanwhile. A run where the rest of the
    machine averaged over 2 cores, or where the server served anyone else, is marked busy; the
    report gives medians with and without busy runs. The lab server listens on its own port
    (8197), not run5's.
- **Warm-up, quiet loopback.**
  - One warm-up run per app and scenario is discarded.
  - Before every run the harness waits until a new connection to the server is made at once
    and fewer than 64 closed connections are still lingering (run5 showed why: a backlog of
    thousands of closed sockets slows whoever runs next).
- **Restarts.** The GUI apps are restarted for every scenario, so nothing they learn about the
  server (a connection limit, say) carries into the next one.
- **Statistics.** 5 measured runs per app and scenario: median, interquartile range, minimum
  and maximum. Failed runs are counted and shown, never dropped.

## Limits

- **A loopback is not the internet.** It has no distance and no packet loss; the faults stand
  in for them. Results come from one machine.
- **Hand-offs differ.** Each app is reached the way it offers, and those ways differ: an HTTP
  call, a bridge process, a command line. The time includes that hand-off. For the
  command-line tools it includes the program starting, which for XDM means starting Java.
- **IDM's numbers are from run5**, 7 days earlier, with the harness of that time. IDM was not
  run again, at the request of the PC's owner. Run5 measured CPU time and peak memory but not
  the peak CPU or idle memory.
- **Gopeed's status checks.** Asking Gopeed for a task's status every 50 ms costs it some CPU,
  which is counted in its numbers.

## Run it yourself

1. Build MDM and the lab server: `cargo build --release -p mdm-app -p mdm-labserver`.
2. Put the other apps under `C:\mdm-bench\apps\<name>` as above (`abdm`, `fdm`, `gopeed`,
   `prism`, `xdm`, `aria2`). Start each GUI app once on the hidden desktop
   (`python tools/bench/launch.py --seconds 15 -- <app.exe>`), so it writes its settings files.
3. Run `python tools/bench/compare.py` (`--only`, `--clients`, `--runs` and `--profiles`
   narrow it down).
4. Run `python tools/bench/compare_report.py C:\mdm-bench\results\<run>` for the tables.

Some of these apps register themselves with the system when they start:

- autostart entries;
- browser native hosts;
- Gopeed takes the `.torrent` and `magnet:` handlers.

`compare.py` removes those that point into `C:\mdm-bench\apps` when it finishes.
`tools/bench/sysstate.ps1` snapshots the registry keys, folders, tasks, services and firewall
rules an installer may touch, and compares two snapshots.
