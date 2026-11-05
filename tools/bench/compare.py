"""Mister Download Manager and other download managers: the same downloads from the same local
lab server, timed, with their CPU, memory and the result checked byte for byte.

    python tools/bench/compare.py [--runs N] [--only scenario,...] [--clients a,b] [--profiles matched,defaults]
                                  [--out DIR]

Before a run, install the other managers as docs/benchmarks.md says (portable copies under
C:\\mdm-bench\\apps) and build MDM and the lab server in release mode.

Every GUI app runs on a separate desktop that is never shown, so nothing appears on the screen
and no mouse or keyboard input is needed: each is driven through the hand-off it offers a
browser or a script (see CLIENTS). The command-line tools run without a window.

Per run:
  * time: the hand-off (or the command) issued -> every file complete, as the app itself says
    (its API or database, a renamed partial file, or the command's exit), on a monotonic clock;
  * correctness: the SHA-256 of every file against the lab server's generator (content.py);
  * CPU: seconds used by the app's processes during the run (and by its hand-off helper, which
    a browser would start too); average = CPU seconds / wall time, in cores; peak = the busiest
    100 ms, in cores;
  * memory: the highest working set of the app's processes during the run; for apps that stay
    running, also their working set 3 s after the run ("idle after");
  * from the server's log: connections and requests.
Clients alternate: the order rotates on every run. One warm-up run per client and scenario is
discarded. Raw results: DIR/runs.json, DIR/server.jsonl, DIR/environment.json.
"""

import argparse
import datetime as dt
import faulthandler
import json
import os
import platform
import random
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import winreg
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402  (settle: wait for a quiet loopback between runs)
import content  # noqa: E402
import winproc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")) / "release"
MDM_EXE = TARGET / "misterdownloadmanager.exe"
LAB_EXE = TARGET / "labserver.exe"
BENCH = Path(os.environ.get("MDM_BENCH_DIR", r"C:\mdm-bench"))
APPS = BENCH / "apps"
DEST = BENCH / "dl"
PORT = 8097
bench.PORT = PORT
LAB = f"http://127.0.0.1:{PORT}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# id, title, size, files, faults, runs, timeout s. The first four are run5's (docs/bench/run5),
# so IDM's numbers from that run can stand beside them.
SCENARIOS = [
    ("fast-1g", "1 GiB over a fast local link", "1G", 1, "", 5, 300),
    ("capped-100m", "100 MiB, 2 MB/s per connection", "100M", 1, "rate=2M", 5, 300),
    ("drops-50m", "50 MiB, every 2nd connection cut after 2 MiB, 4 MB/s", "50M", 1,
     "rate=4M&drop_after=2M&drop_every=2", 5, 300),
    ("maxconns-50m", "50 MiB, server allows 2 connections, 2 MB/s each", "50M", 1, "rate=2M&max_conns=2", 5, 300),
    ("norange-100m", "100 MiB from a server without range support", "100M", 1, "no_range=1", 5, 300),
    ("batch-32x256k", "32 small files (256 KiB each)", "256K", 32, "", 5, 300),
]


def size_bytes(s):
    n, u = s[:-1], s[-1].upper()
    return int(float(n) * {"K": 2**10, "M": 2**20, "G": 2**30}[u])


def http_json(url, body=None, headers=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class NativeHost:
    """A browser's side of native messaging: 4-byte length + JSON on the host's stdin/stdout."""

    def __init__(self, exe, origin):
        self.p = subprocess.Popen([str(exe), origin], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        self.pid = self.p.pid

    def send(self, msg):
        b = json.dumps(msg).encode()
        self.p.stdin.write(struct.pack("<I", len(b)) + b)
        self.p.stdin.flush()

    def recv(self):
        h = self.p.stdout.read(4)
        if len(h) < 4:
            raise EOFError("native host closed")
        return json.loads(self.p.stdout.read(struct.unpack("<I", h)[0]))

    def call(self, msg):
        self.send(msg)
        return self.recv()

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(10)
        except Exception:
            self.p.kill()


# ---- clients ------------------------------------------------------------------------------
class Client:
    name = ""
    label = ""
    resident = True  # stays running between downloads (a GUI app)
    default_conns = 8

    def version(self):
        return ""

    def prepare(self, conns):
        """Write the settings for a session (before start)."""

    def start(self, desk):
        """Start the app on `desk`; return its root process id."""

    def ready(self):
        return True

    def add(self, items, conns):
        """Hand the downloads over; return (state, [helper pids])."""

    def done(self, state, items):
        """True when the app says every download is complete (or failed: then raise)."""

    def finished_ms(self, state, items):
        return None

    def stop(self):
        pass


def kill_tree(pid):
    for q in reversed(winproc.tree(pid)):
        subprocess.run(["taskkill", "/F", "/PID", str(q)], capture_output=True)


def file_version(path):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{path}').VersionInfo.ProductVersion"],
                       capture_output=True, text=True)
    return r.stdout.strip()


class Mdm(Client):
    name, label = "MDM", "Mister Download Manager"
    data = BENCH / "mdm-data"

    def version(self):
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
        return f"{file_version(MDM_EXE)} ({sha})"

    def env(self):
        return dict(os.environ, MDM_DATA_DIR=str(self.data), MDM_OFFSCREEN="1")

    def prepare(self, conns):
        f = self.data / "downloads.json"
        if not f.exists():
            # First start writes the defaults; then the bench's own choices are set in it.
            self.data.mkdir(parents=True, exist_ok=True)
            p = winproc.popen_on(self.desk_for_prepare, [str(MDM_EXE)], env=self.env())
            for _ in range(100):
                time.sleep(0.1)
                if f.exists():
                    break
            time.sleep(1)
            kill_tree(p.pid)
        d = json.loads(f.read_text(encoding="utf-8"))
        d["items"] = []
        d["settings"].update(max_connections=conns, clipboard_autostart=False, launch_on_startup=False,
                             update_check=False, language_asked=True, helpers_asked=True,
                             extension_never_ask=True, show_complete=False, torrent_associations=False,
                             grabber_check=False)
        f.write_text(json.dumps(d, indent=1), encoding="utf-8")

    def start(self, desk):
        self.p = winproc.popen_on(desk, [str(MDM_EXE)], env=self.env())
        self.desk = desk
        return self.p.pid

    def ready(self):
        return (self.data / "ipc.json").exists()

    def add(self, items, conns):
        helpers = []
        for url, name in items:
            h = winproc.popen_on(self.desk, [str(MDM_EXE), "/d", url, "/p", str(DEST), "/f", name, "/n"],
                                 env=self.env())
            helpers.append(h)
        return None, helpers

    def done(self, state, items):
        # MDM writes `name.mdm.part` and renames it into place when complete.
        return all((DEST / n).exists() and not (DEST / (n + ".mdm.part")).exists() for _, n in items)

    def stop(self):
        kill_tree(self.p.pid)


class Abdm(Client):
    name, label = "ABDM", "AB Download Manager"
    exe = APPS / "abdm" / "ABDownloadManager" / "ABDownloadManager.exe"
    home = Path.home() / ".abdm"
    key = "mdm-bench-71-local-key"

    def version(self):
        return file_version(self.exe)

    def prepare(self, conns):
        f = self.home / "config" / "appSettings.json"
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        d.update(autoStartOnBoot=False, threadCount=conns, defaultDownloadFolder=str(DEST),
                 showDownloadCompletionDialog=False, showDownloadProgressDialog=False, notificationSound=False,
                 useCategoryByDefault=False, apiEnabled=True, apiPort=15151, apiAuthKey=self.key)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=1), encoding="utf-8")

    def start(self, desk):
        self.p = winproc.popen_on(desk, [str(self.exe)], cwd=str(self.exe.parent))
        return self.p.pid

    def ready(self):
        try:
            http_json("http://localhost:15151/queues", timeout=1)
            return True
        except Exception:
            return False

    def add(self, items, conns):
        # Each call answers only after about 2 s, so several files are handed over at once,
        # as quickly as a person clicking them one after another would.
        def one(item):
            url, name = item
            http_json("http://localhost:15151/start-headless-download",
                      {"downloadSource": {"link": url}, "folder": DEST.as_posix(), "name": name,
                       "startDownload": True}, {"X-Api-Key": self.key}, timeout=60)

        with ThreadPoolExecutor(max_workers=len(items)) as pool:
            list(pool.map(one, items))
        return None, []

    def _entries(self, items):
        names = {n for _, n in items}
        out = {}
        for f in (self.home / "config" / "download_db" / "downloadlist").glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue  # being written
            if d.get("name") in names and Path(d.get("folder", "")).resolve() == DEST.resolve():
                out[d["name"]] = d
        return out

    def done(self, state, items):
        e = self._entries(items)
        if any(d.get("status") == "Error" for d in e.values()):
            raise RuntimeError("ABDM reports an error")
        return len(e) == len(items) and all(d.get("status") == "Completed" for d in e.values())

    def finished_ms(self, state, items):
        e = self._entries(items)
        t = [d.get("completeTime") for d in e.values()]
        return max(t) if t and all(t) else None

    def stop(self):
        kill_tree(self.p.pid)


class Gopeed(Client):
    name, label = "Gopeed", "Gopeed"
    dir = APPS / "gopeed"
    origin = "chrome-extension://mijpgljlfcapndmchhjffkpckknofcnd/"
    default_conns = 16

    def version(self):
        return file_version(self.dir / "gopeed.exe")

    def start(self, desk):
        self.p = winproc.popen_on(desk, [str(self.dir / "gopeed.exe")], cwd=str(self.dir))
        self.poll_host = None
        return self.p.pid

    def forward(self, host, method, path, data=None):
        r = host.call({"method": "forward", "params": {"method": method, "path": path,
                                                      **({"data": data} if data is not None else {})}})
        if r.get("code") != 0 or r["data"].get("code") != 0:
            raise RuntimeError(f"Gopeed: {r}")
        return r["data"]["data"]

    def ready(self):
        try:
            h = NativeHost(self.dir / "host.exe", self.origin)
            if h.call({"method": "ping"}).get("data") is not True:
                h.close()
                return False
            cfg = self.forward(h, "GET", "/api/v1/config")
            cfg["downloadDir"] = str(DEST)
            cfg.setdefault("extra", {}).update(desktopNotification=False, notifyWhenNewVersion=False)
            self.forward(h, "PUT", "/api/v1/config", cfg)
            self.poll_host = h
            return True
        except Exception:
            return False

    def add(self, items, conns):
        ids, helpers = [], []
        for url, name in items:
            # One host per hand-off, as a browser's one-shot message starts one.
            h = NativeHost(self.dir / "host.exe", self.origin)
            helpers.append(h.p)
            opts = {"name": name, "path": str(DEST)}
            if conns != self.default_conns:
                opts["extra"] = {"connections": conns}
            ids.append(self.forward(h, "POST", "/api/v1/tasks", {"req": {"url": url}, "opts": opts}))
            h.close()
        return ids, helpers

    def done(self, state, items):
        # Asking costs Gopeed some CPU (counted in its numbers): one question every 50 ms, about
        # the first task not yet known to be done.
        now = time.perf_counter()
        if now - getattr(self, "_asked", 0) < 0.05:
            return False
        self._asked = now
        while state:
            st = self.forward(self.poll_host, "GET", f"/api/v1/tasks/{state[0]}")["status"]
            if st == "error":
                raise RuntimeError("Gopeed reports an error")
            if st != "done":
                return False
            state.pop(0)
        return True

    def stop(self):
        if self.poll_host:
            self.poll_host.close()
        kill_tree(self.p.pid)


class Prism(Client):
    name, label = "Prism", "Prism"
    dir = APPS / "prism"
    origin = "chrome-extension://mmcdeiglkbfbicdjboocmhehodogilfl/"

    def version(self):
        return file_version(self.dir / "prism.exe")

    def prepare(self, conns):
        db = sqlite3.connect(self.dir / "data" / "prism.db")
        s = json.loads(db.execute("select value from settings where key='settings'").fetchone()[0])
        s["general"].update(launchAtStartup=False, startMinimized=False, showCaptureDialog=False,
                            showProgressWindow=False, showCompletionDialog=False, notifications=False,
                            checkUpdates=False)
        s["onboardingDone"] = True
        s["downloads"].update(defaultDir=str(DEST), useCategoryFolders=False, conflict="overwrite", autoStart=True,
                              defaultConnections=conns)
        s["sounds"]["enabled"] = False
        s["clipboard"]["monitor"] = False
        s["video"]["autoUpdate"] = False
        db.execute("update settings set value=? where key='settings'", (json.dumps(s),))
        db.commit()
        db.close()

    def start(self, desk):
        self.p = winproc.popen_on(desk, [str(self.dir / "prism.exe")], cwd=str(self.dir))
        return self.p.pid

    def ready(self):
        try:
            h = NativeHost(self.dir / "prism-native-host.exe", self.origin)
            ok = h.call({"type": "hello", "id": 1}).get("ok")
            h.close()
            return bool(ok)
        except Exception:
            return False

    def add(self, items, conns):
        helpers = []
        for i, (url, name) in enumerate(items):
            h = NativeHost(self.dir / "prism-native-host.exe", self.origin)
            helpers.append(h.p)
            r = h.call({"type": "download", "id": i + 2, "url": url, "filename": name, "method": "GET",
                        "cookies": [], "userAgent": UA, "incognito": False, "source": "capture"})
            h.close()
            if not r.get("ok") or r.get("accepted") is False:
                raise RuntimeError(f"Prism declined: {r}")
        return None, helpers

    def done(self, state, items):
        # Prism writes `name.prismpart` and renames it into place when complete.
        return all((DEST / n).exists() and not (DEST / (n + ".prismpart")).exists() for _, n in items)

    def stop(self):
        kill_tree(self.p.pid)


class Fdm(Client):
    name, label = "FDM", "Free Download Manager"
    dir = APPS / "fdm"
    db = Path(os.environ["LOCALAPPDATA"]) / "Softdeluxe" / "Free Download Manager" / "db.sqlite"
    origin = "chrome-extension://ahmpjcflkgiildlgicmcieglgoilbfdp/"
    default_conns = 15

    def version(self):
        return file_version(self.dir / "fdm.exe")

    def prepare(self, conns):
        c = sqlite3.connect(self.db)
        for k, v in [("SilentModeForNewDownloads", "1"), ("DefaultDownloadPath", DEST.as_posix()),
                     ("FixedDownloadPath", DEST.as_posix()), ("DownloadPathDependsOnFileType", "0"),
                     ("DownloadPathDependsOnSourceUrl", "0"), ("NotifyOfAddedDownloads", "0"),
                     ("NotifyOfFinishedDownloads", "0"), ("NotifyOfFailedDownloads", "0"),
                     ("EnableSoundNotifications", "0"), ("CheckUpdatesAutomatically", "0"),
                     ("InstallUpdatesAutomatically", "0"), ("UpdatePluginsAutomatically", "0"),
                     ("ShowSpecialOffers", "0"), ("MaxConnectionsPerServer", str(conns))]:
            c.execute("insert or replace into Settings(Name,Value) values(?,?)", (k, v))
        c.commit()
        c.close()

    def start(self, desk):
        # With its window open, as every other app here (the window is on the hidden desktop).
        self.p = winproc.popen_on(desk, [str(self.dir / "fdm.exe")], cwd=str(self.dir))
        return self.p.pid

    def ready(self):
        try:
            h = NativeHost(self.dir / "wenativehost.exe", self.origin)
            r = h.call({"id": "1", "type": "handshake", "handshake": {"api_version": "1", "browser": "Chrome"}})
            h.close()
            return r.get("type") == "handshake" and bool(r.get("version"))
        except Exception:
            return False

    def add(self, items, conns):
        h = NativeHost(self.dir / "wenativehost.exe", self.origin)
        h.call({"id": "1", "type": "handshake", "handshake": {"api_version": "1", "browser": "Chrome"}})
        # One message per file, as a browser sends one per clicked link (several in one message
        # make a batch that FDM saves into a subfolder named after the server).
        for i, (u, n) in enumerate(items):
            r = h.call({"id": str(i + 2), "type": "create_downloads", "create_downloads": {"downloads": [
                {"url": u, "originalUrl": u, "httpReferer": "", "userAgent": UA, "httpCookies": "",
                 "suggestedName": n}]}})
            if r.get("error"):
                raise RuntimeError(f"FDM: {r}")
        h.close()
        return [u for u, _ in items], [h.p]

    def _rows(self, urls):
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=1)
        try:
            q = ",".join("?" * len(urls))
            return c.execute(f"select url, finishedTime from downloads where url in ({q})", urls).fetchall()
        finally:
            c.close()

    def done(self, state, items):
        try:
            rows = self._rows(state)
        except sqlite3.Error:
            return False
        return len(rows) == len(state) and all(t for _, t in rows)

    def stop(self):
        kill_tree(self.p.pid)


class Cli(Client):
    resident = False

    def start(self, desk):
        return None

    def command(self, items, conns):
        raise NotImplementedError

    def add(self, items, conns):
        self.p = subprocess.Popen(self.command(items, conns), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW, cwd=str(DEST))
        return self.p, [self.p]

    def done(self, state, items):
        code = state.poll()
        if code is None:
            return False
        if code != 0:
            raise RuntimeError(f"{self.name} exited with {code}")
        return True


class Aria2(Cli):
    name, label = "aria2", "aria2c"
    exe = APPS / "aria2" / "aria2-1.37.0-win-64bit-build1" / "aria2c.exe"
    default_conns = 1

    def version(self):
        out = subprocess.run([str(self.exe), "--version"], capture_output=True, text=True).stdout
        return out.splitlines()[0].replace("aria2 version ", "")

    def command(self, items, conns):
        cmd = [str(self.exe), "-d", str(DEST), "--allow-overwrite=true", "--auto-file-renaming=false",
               "--console-log-level=warn", "--summary-interval=0", "--file-allocation=none", "-U", UA]
        if conns != self.default_conns:
            # -k: aria2 splits a file only into parts of at least 20 MiB by default.
            cmd += [f"-x{conns}", f"-s{conns}", "-k1M"]
        if len(items) == 1:
            return cmd + ["-o", items[0][1], items[0][0]]
        lst = BENCH / "aria2-input.txt"
        lst.write_text("".join(f"{u}\n out={n}\n" for u, n in items), encoding="utf-8")
        return cmd + ["-i", str(lst)]


class Curl(Cli):
    name, label = "curl", "curl"
    exe = Path(os.environ["SystemRoot"]) / "System32" / "curl.exe"
    default_conns = 1

    def version(self):
        out = subprocess.run([str(self.exe), "--version"], capture_output=True, text=True).stdout
        return out.split()[1]  # "curl 8.21.0 (Windows) libcurl/..."

    def command(self, items, conns):
        cmd = [str(self.exe), "-sS", "--fail", "-A", UA]
        for u, n in items:
            cmd += ["-o", str(DEST / n), u]
        return cmd


class Xdm(Cli):
    name, label = "XDM", "Xtreme Download Manager"
    exe = APPS / "xdm" / "PFiles64" / "XDM" / "xdm-app.exe"

    def version(self):
        return "9.0.9"

    def command(self, items, conns):
        cmd = [str(self.exe), "--headless", "-o", str(DEST), "-y", "--quiet", "-s", str(conns), "-A", UA]
        if len(items) == 1:
            cmd += ["-f", items[0][1]]
        return cmd + [u for u, _ in items]


CLIENTS = {c.name: c for c in (Mdm(), Abdm(), Gopeed(), Prism(), Fdm(), Xdm(), Aria2(), Curl())}


# ---- registrations the apps add on every start --------------------------------------------
def restore_registrations():
    """Remove what the benchmarked apps (re)write into HKCU on every start: autostart values,
    browser native hosts, and Gopeed's .torrent / magnet / gopeed: handlers. Only entries that
    point into the benchmark's apps folder are touched."""
    removed = []
    apps = str(APPS).lower()

    def walk_delete(root, path):
        try:
            k = winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
        except OSError:
            return
        while True:
            try:
                sub = winreg.EnumKey(k, 0)
            except OSError:
                break
            walk_delete(root, path + "\\" + sub)
        winreg.CloseKey(k)
        winreg.DeleteKey(root, path)

    def mentions_apps(root, path):
        def scan(p):
            try:
                k = winreg.OpenKey(root, p)
            except OSError:
                return False
            i = 0
            while True:
                try:
                    _, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if apps in str(v).lower():
                    return True
                i += 1
            j = 0
            while True:
                try:
                    s = winreg.EnumKey(k, j)
                except OSError:
                    break
                if scan(p + "\\" + s):
                    return True
                j += 1
            return False

        return scan(path)

    hk = winreg.HKEY_CURRENT_USER
    run = r"Software\Microsoft\Windows\CurrentVersion\Run"
    approved = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    with winreg.OpenKey(hk, run, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        names = []
        i = 0
        while True:
            try:
                n, v, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            if apps in str(v).lower():
                names.append(n)
            i += 1
        for n in names:
            winreg.DeleteValue(k, n)
            removed.append(f"HKCU\\{run}\\{n}")
            try:
                with winreg.OpenKey(hk, approved, 0, winreg.KEY_WRITE) as a:
                    winreg.DeleteValue(a, n)
                    removed.append(f"HKCU\\{approved}\\{n}")
            except OSError:
                pass
    for vendor in (r"Google\Chrome", "Chromium", r"Microsoft\Edge", r"BraveSoftware\Brave-Browser", "Vivaldi",
                   "Opera Software", "Mozilla"):
        base = f"Software\\{vendor}\\NativeMessagingHosts"
        try:
            k = winreg.OpenKey(hk, base)
        except OSError:
            continue
        subs = []
        i = 0
        while True:
            try:
                subs.append(winreg.EnumKey(k, i))
            except OSError:
                break
            i += 1
        winreg.CloseKey(k)
        for s in subs:
            p = f"{base}\\{s}"
            v = ""
            try:
                v = winreg.QueryValue(hk, p)
            except OSError:
                pass
            # The key's default value names a manifest; the apps keep theirs in their folder
            # (or ABDM's in ~/.abdm).
            if apps in v.lower() or ".abdm" in v.lower() or mentions_apps(hk, p):
                walk_delete(hk, p)
                removed.append(f"HKCU\\{p}")
    for cls in (r"Software\Classes\.torrent", r"Software\Classes\magnet", r"Software\Classes\gopeed",
                r"Software\Classes\Gopeed_torrent"):
        try:
            v = winreg.QueryValue(hk, cls)
        except OSError:
            continue
        if mentions_apps(hk, cls) or v == "Gopeed_torrent":
            walk_delete(hk, cls)
            removed.append(f"HKCU\\{cls}")
    return removed


# ---- runs ---------------------------------------------------------------------------------
def settle(limit=240, linger_max=64):
    """Wait until the loopback is quiet before a run (bench.settle's idea, run5): a new
    connection to the server is made at once and no backlog of closed connections lingers. A
    few dozen sockets in TIME_WAIT (what any app's cut or finished connections leave for up to
    two minutes) don't slow a new connection; thousands do, so the bar is set at 64."""
    a = time.perf_counter()
    first = bench.lingering()
    while time.perf_counter() - a < limit:
        if bench.lingering() <= linger_max and max(bench.connect_ms() for _ in range(3)) < 5:
            break
        time.sleep(1)
    return round((time.perf_counter() - a) * 1000), first


def clear_dest():
    for f in DEST.iterdir():
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)


def server_up(log):
    lab = subprocess.Popen([str(LAB_EXE), "--bind", f"127.0.0.1:{PORT}", "--log-file", str(log)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{LAB}/gen/1", timeout=1).read()
            return lab
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("lab server didn't start")


def one_run(client, items, expect, conns, timeout, resident_pid):
    # A 1-byte request just before: its midpoint on our clock against its start in the server's
    # log puts the server's times on our clock (loopback: within about a millisecond).
    a = time.perf_counter()
    urllib.request.urlopen(f"{LAB}/gen/1/cal-{items[0][1]}", timeout=5).read()
    cal_ms = (a + time.perf_counter()) / 2 * 1000
    usage = winproc.Usage([resident_pid] if resident_pid else [], period=0.1)
    usage.start()
    t0 = time.perf_counter()
    wall0 = time.time()
    err = None
    state = None
    helpers = []
    try:
        state, helpers = client.add(items, conns)
        for h in helpers:
            usage.add_root(h.pid)
        t_added = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if client.done(state, items):
                break
            time.sleep(0.005)
        else:
            err = "timeout"
    except Exception as e:  # noqa: BLE001 - reported as a failed run
        err = str(e)[:300]
        t_added = None
    t1 = time.perf_counter()
    cpu = usage.stop()
    wall = t1 - t0
    finished = client.finished_ms(state, items) if err is None else None
    idle = None
    if resident_pid:
        time.sleep(3)
        idle = sum(winproc.Proc(p).mem()[0] for p in winproc.tree(resident_pid))
    # Correctness: every file, byte for byte.
    sha_ok, sizes, bad = True, 0, []
    for (url, name), (seed, size, digest) in zip(items, expect):
        p = DEST / name
        if not p.exists():
            sha_ok = False
            bad.append(f"{name}: missing")
            continue
        if p.stat().st_size != size:
            sha_ok = False
            bad.append(f"{name}: {p.stat().st_size} bytes")
            continue
        sizes += size
        if content.file_sha256(p) != digest:
            sha_ok = False
            bad.append(f"{name}: wrong content")
    if bad:
        bad.append("folder: " + ", ".join(sorted(f.name for f in DEST.iterdir()))[:2000])
    return {
        "ok": err is None,
        "error": err,
        "sha_ok": sha_ok if err is None else None,
        "e2e_ms": round(wall * 1000, 1) if err is None else None,
        "handoff_ms": round((t_added - t0) * 1000, 1) if t_added else None,
        "t0_wall_ms": round(wall0 * 1000),
        "t0_ms": round(t0 * 1000, 3),
        "done_ms": round(t1 * 1000, 3),
        "cal_ms": round(cal_ms, 3),
        "app_finished_wall_ms": finished,
        "cpu_s": round(cpu, 3),
        "cpu_avg_cores": round(cpu / wall, 3) if wall > 0 else None,
        "cpu_peak_cores": round(usage.peak_cpu, 3),
        "others_avg_cores": round(usage.others_avg(), 3),
        "others_peak_cores": round(usage.peak_others, 3),
        "peak_mem_mb": round(usage.peak_mem / 2**20, 1),
        "idle_after_mb": round(idle / 2**20, 1) if idle is not None else None,
        "bytes": sizes,
        "bad_files": bad,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=None, help="measured runs per scenario (0: the warm-up only)")
    ap.add_argument("--only", default="")
    ap.add_argument("--clients", default=",".join(CLIENTS))
    ap.add_argument("--profiles", default="matched,defaults")
    ap.add_argument("--out", default=str(BENCH / "results" / dt.datetime.now().strftime("%Y%m%d-%H%M")))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # A stuck run leaves its stack here every 5 minutes.
    faulthandler.dump_traceback_later(int(os.environ.get("MDM_BENCH_STACKS", "300")), repeat=True, file=open(out / "stacks.txt", "w"))
    DEST.mkdir(parents=True, exist_ok=True)
    clear_dest()
    clients = [CLIENTS[c] for c in a.clients.split(",")]
    scen = [s for s in SCENARIOS if not a.only or s[0] in a.only.split(",")]
    desk = winproc.Desk("mdm-bench")
    Mdm.desk_for_prepare = desk

    env = {
        "date": dt.datetime.now().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "cpu": subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                              capture_output=True, text=True).stdout.strip(),
        "ram_gb": round(int(subprocess.run(["powershell", "-NoProfile", "-Command",
                                            "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                                           capture_output=True, text=True).stdout.strip()) / 2**30, 1),
        "disk": f"{DEST.drive} (every app's destination)",
        "server": f"labserver (this repo), 127.0.0.1:{PORT}, generated content",
        "clients": {c.name: {"label": c.label, "version": c.version(), "default_connections": c.default_conns}
                    for c in clients},
    }
    (out / "environment.json").write_text(json.dumps(env, indent=1))
    print(json.dumps(env["clients"], indent=1), flush=True)

    # Expected digests, once per (seed, size).
    digests = {}

    def expected(seed, size):
        if (seed, size) not in digests:
            digests[(seed, size)] = content.sha256(seed, size)
        return digests[(seed, size)]

    lab = server_up(out / "server.jsonl")
    runs = []
    try:
        for profile in a.profiles.split(","):
            for sid, title, size, nfiles, faults, n, timeout in scen:
                if profile == "defaults" and sid not in ("fast-1g", "capped-100m"):
                    continue
                # curl has no connection setting: one profile says it all.
                active = [c for c in clients if profile == "matched" or (c.default_conns != 8 and c.name != "curl")]
                if not active:
                    continue
                n = n if a.runs is None else a.runs
                # curl has one connection whatever it is asked.
                conns = {c.name: (1 if c.name == "curl" else 8 if profile == "matched" else c.default_conns)
                         for c in active}
                print(f"== {profile} / {sid}: {title} ({n} runs + warm-up) {', '.join(c.name for c in active)}",
                      flush=True)
                roots = {}
                for c in active:
                    if c.resident:
                        c.prepare(conns[c.name])
                        roots[c.name] = c.start(desk)
                for c in active:
                    if c.resident:
                        for _ in range(600):
                            if c.ready():
                                break
                            time.sleep(0.1)
                        else:
                            raise RuntimeError(f"{c.name} didn't start")
                time.sleep(3)
                for i in range(-1, n):
                    # A new random order every round (seeded: the order can be repeated), so
                    # load from other programs falls on every app alike.
                    order = list(active)
                    random.Random(f"{profile}/{sid}/{i}").shuffle(order)
                    for pos, c in enumerate(order):
                        tag = "w" if i < 0 else f"{i:02d}"
                        items, expect = [], []
                        for j in range(nfiles):
                            seed = 1000 + (i + 1) * 100 + j
                            name = f"{sid}-{profile[0]}-{c.name.lower()}-{tag}" + (f"-{j:02d}" if nfiles > 1 else "") + ".bin"
                            q = f"seed={seed}" + (f"&{faults}" if faults else "")
                            items.append((f"{LAB}/gen/{size}/{name}?{q}", name))
                            expect.append((seed, size_bytes(size), expected(seed, size_bytes(size))))
                        settle_ms, lingered = settle()
                        r = one_run(c, items, expect, conns[c.name], timeout, roots.get(c.name))
                        r.update(client=c.name, profile=profile, connections_setting=conns[c.name], scenario=sid,
                                 run=i, warmup=i < 0, position=pos, files=[n for _, n in items], settle_ms=settle_ms,
                                 lingering_before=lingered)
                        runs.append(r)
                        print(f"  {tag} {c.name:7} {r['e2e_ms']} ms  sha {r['sha_ok']}  cpu {r['cpu_s']} s "
                              f"(avg {r['cpu_avg_cores']}, peak {r['cpu_peak_cores']})  mem {r['peak_mem_mb']} MB"
                              f"  idle {r['idle_after_mb']}  others {r['others_avg_cores']}{'' if r['ok'] else '  FAILED: ' + str(r['error'])}",
                              flush=True)
                        if not c.resident and c.p.poll() is None:
                            kill_tree(c.p.pid)
                        clear_dest()
                        (out / "runs.json").write_text(json.dumps(runs, indent=1))
                        time.sleep(0.5)
                for c in active:
                    if c.resident:
                        c.stop()
                time.sleep(2)
    finally:
        for c in clients:
            if c.resident and getattr(c, "p", None) is not None:
                try:
                    c.stop()
                except Exception:
                    pass
        lab.terminate()
        removed = restore_registrations()
        (out / "restored.json").write_text(json.dumps(removed, indent=1))
        print("restored:", removed, flush=True)
    print(f"done: {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
