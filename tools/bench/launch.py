"""Start a program on the benchmark's hidden desktop and keep it there (for setting up and
exploring an app without showing it on the screen). Stops it (and its process tree) on Enter
or when stdin closes, or after --seconds.

    python tools/bench/launch.py [--seconds N] -- program args...
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import winproc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--keep", action="store_true", help="leave it running (prints its pid)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    desk = winproc.Desk()
    p = winproc.popen_on(desk, cmd, cwd=str(Path(cmd[0]).parent))
    print("pid", p.pid, flush=True)
    t0 = time.time()
    while a.seconds == 0 or time.time() - t0 < a.seconds:
        time.sleep(1)
        if p.poll() is not None:
            print("exited", p.returncode, flush=True)
            break
    for hwnd, pid, title, vis in desk.windows():
        if vis or title:
            print(f"window {hwnd} pid {pid} visible={vis} {title!r}")
    print("tree", [(q, winproc.processes().get(q, ("", "?"))[1]) for q in winproc.tree(p.pid)], flush=True)
    if not a.keep:
        for q in reversed(winproc.tree(p.pid)):
            subprocess.run(["taskkill", "/F", "/PID", str(q)], capture_output=True)
    desk.close() if not a.keep else None


if __name__ == "__main__":
    main()
