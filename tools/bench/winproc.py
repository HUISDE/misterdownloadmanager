"""Windows process helpers for the comparison benchmark (tools/bench/compare.py).

* `Desk`: a separate, never-shown desktop. Apps started on it draw their windows there, so
  they can't cover or take the focus from the person using the PC, and no real mouse or
  keyboard input is ever needed (or possible) there.
* `tree(pid)`: a process and all its descendants; `Usage`: CPU time and working set of a
  process tree, sampled, for peak / average CPU and peak memory.
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import threading
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
user32.CreateDesktopW.restype = wt.HANDLE
user32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wt.HANDLE]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumDesktopWindows.argtypes = [wt.HANDLE, WNDENUMPROC, wt.LPARAM]

GENERIC_ALL = 0x10000000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def processes():
    """{pid: (parent pid, image name)} of every process now."""
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    out = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    kernel32.CloseHandle(snap)
    return out


def tree(root, procs=None):
    """`root` and every process descended from it (a parent id can be reused by Windows, so a
    child must have started after its parent: checked through the creation times)."""
    procs = procs if procs is not None else processes()
    kids = {}
    for pid, (ppid, _) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    out, todo = [], [root] if root in procs else []
    while todo:
        p = todo.pop()
        out.append(p)
        for k in kids.get(p, []):
            if k != p and k not in out and created(k) >= created(p):
                todo.append(k)
    return out


def created(pid):
    """When the process now holding `pid` started (not cached: Windows reuses ids)."""
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return 0
    c, e, k, u = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    kernel32.CloseHandle(h)
    return c.dwHighDateTime << 32 | c.dwLowDateTime


class Proc:
    """An open handle to one process: its CPU seconds and memory, readable after it exits."""

    def __init__(self, pid):
        self.pid = pid
        self.h = kernel32.OpenProcess(0x1000 | 0x0010 | 0x00100000, False, pid)  # query, read, SYNCHRONIZE

    def cpu(self):
        c, e, k, u = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not self.h or not kernel32.GetProcessTimes(self.h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k),
                                                      ctypes.byref(u)):
            return 0.0
        t = lambda f: (f.dwHighDateTime << 32 | f.dwLowDateTime) / 1e7
        return t(k) + t(u)

    def mem(self):
        m = PMC()
        m.cb = ctypes.sizeof(PMC)
        if not self.h or not psapi.GetProcessMemoryInfo(self.h, ctypes.byref(m), m.cb):
            return 0, 0
        return m.WorkingSetSize, m.PeakWorkingSetSize

    def alive(self):
        return bool(self.h) and kernel32.WaitForSingleObject(self.h, 0) == 0x102  # WAIT_TIMEOUT

    def close(self):
        if self.h:
            kernel32.CloseHandle(self.h)
            self.h = None


def system_busy():
    """CPU seconds the whole machine has spent busy (all processors) since it started."""
    i, k, u = wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    t = lambda f: (f.dwHighDateTime << 32 | f.dwLowDateTime) / 1e7
    return t(k) + t(u) - t(i)  # kernel time includes idle time


class Usage(threading.Thread):
    """CPU and memory of every process in the trees of `roots` (new children are picked up as
    they appear), sampled every `period` seconds until `.stop()`.

    peak_cpu: the highest CPU use over any one sample period, in cores (1.0 = one core busy);
    cpu: CPU seconds used in all; peak_mem: the highest sum of working sets seen."""

    def __init__(self, roots, period=0.1):
        super().__init__(daemon=True)
        self.roots, self.period = list(roots), period
        self.procs = {}
        self.base = {}
        self.halt = threading.Event()
        self.peak_cpu = 0.0
        self.peak_mem = 0
        self.samples = []
        self.lock = threading.Lock()
        self._scan()

    def add_root(self, pid):
        """A process started for the run (a hand-off helper): counted from its start, even if
        it has already exited (the caller must still hold a handle to it)."""
        with self.lock:
            self.roots.append(pid)
            if pid not in self.procs:
                self.procs[pid] = Proc(pid)
                self.base[pid] = 0.0

    def _scan(self):
        procs = processes()
        first = not self.samples
        with self.lock:
            roots = list(self.roots)
            for r in roots:
                for p in tree(r, procs):
                    if p not in self.procs:
                        pr = Proc(p)
                        self.procs[p] = pr
                        # Processes there before the run count from now; new ones from their start.
                        self.base[p] = pr.cpu() if first else 0.0

    def total_cpu(self):
        with self.lock:
            items = list(self.procs.items())
        return sum(max(0.0, p.cpu() - self.base[pid]) for pid, p in items)

    def mem_now(self):
        with self.lock:
            ps = list(self.procs.values())
        return sum(p.mem()[0] for p in ps if p.alive())

    def run(self):
        last_t, last_c, last_s = time.perf_counter(), self.total_cpu(), system_busy()
        self.t_first, self.c_first, self.s_first = last_t, last_c, last_s
        self.peak_others = 0.0
        self.samples.append((last_t, last_c, self.mem_now()))
        n = 0
        while not self.halt.wait(self.period):
            n += 1
            if n % 5 == 0:
                self._scan()
            t, c, m, s = time.perf_counter(), self.total_cpu(), self.mem_now(), system_busy()
            self.samples.append((t, c, m))
            dt_ = max(t - last_t, 1e-6)
            self.peak_cpu = max(self.peak_cpu, (c - last_c) / dt_)
            # Everything else the machine did meanwhile (other programs, the system).
            self.peak_others = max(self.peak_others, max(0.0, (s - last_s) - (c - last_c)) / dt_)
            self.peak_mem = max(self.peak_mem, m)
            last_t, last_c, last_s = t, c, s
        self.t_last, self.c_last, self.s_last = last_t, last_c, last_s

    def others_avg(self):
        """Average CPU use, in cores, of everything but the measured processes during the run."""
        span = self.t_last - self.t_first
        if span <= 0:
            return 0.0
        return max(0.0, (self.s_last - self.s_first) - (self.c_last - self.c_first)) / span

    def stop(self):
        self.halt.set()
        self.join()
        self._scan()
        for p in self.procs.values():
            # A process that exited between samples: its own peak counts too.
            if not p.alive():
                self.peak_mem = max(self.peak_mem, p.mem()[1])
        return self.total_cpu()


class Desk:
    """A desktop nobody sees. `startupinfo()` puts a new process (and its windows) on it."""

    def __init__(self, name="mdm-bench"):
        self.name = name
        self.h = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
        if not self.h:
            raise OSError(ctypes.get_last_error(), "CreateDesktop")

    def windows(self):
        """(hwnd, pid, title) of every top-level window on this desktop."""
        out = []

        def cb(hwnd, _):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            out.append((hwnd, pid.value, buf.value, bool(user32.IsWindowVisible(hwnd))))
            return True

        user32.EnumDesktopWindows(self.h, WNDENUMPROC(cb), 0)
        return out

    def close(self):
        if self.h:
            user32.CloseDesktop(self.h)
            self.h = None


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD)]


kernel32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                    ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                    ctypes.POINTER(PROCESS_INFORMATION)]


class DeskProcess:
    """A process started on a desktop (Python's subprocess can't choose the desktop)."""

    def __init__(self, pid, handle):
        self.pid, self._h, self.returncode = pid, handle, None

    def poll(self):
        if self.returncode is None and kernel32.WaitForSingleObject(self._h, 0) == 0:
            code = wt.DWORD()
            kernel32.GetExitCodeProcess(self._h, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if kernel32.WaitForSingleObject(self._h, ms) != 0:
            raise subprocess.TimeoutExpired("process", timeout)
        return self.poll()


def popen_on(desk, args, cwd=None, env=None, **kw):
    """Start `args` on `desk` (its windows land there, never on the screen). With desk None:
    subprocess.Popen without a console window."""
    if desk is None:
        kw.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        return subprocess.Popen(args, cwd=cwd, env=env, **kw)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = f"winsta0\\{desk.name}"
    si.dwFlags = 0x1  # STARTF_USESHOWWINDOW
    si.wShowWindow = 7  # SW_SHOWMINNOACTIVE, for apps that honour it
    pi = PROCESS_INFORMATION()
    block = None
    flags = 0x08000000  # CREATE_NO_WINDOW (console programs)
    if env is not None:
        flags |= 0x400  # CREATE_UNICODE_ENVIRONMENT
        block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0")
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
    if not kernel32.CreateProcessW(None, cmd, None, None, False, flags, block, cwd, ctypes.byref(si),
                                   ctypes.byref(pi)):
        raise OSError(ctypes.get_last_error(), f"CreateProcess {args[0]}")
    kernel32.CloseHandle(pi.hThread)
    return DeskProcess(pi.dwProcessId, pi.hProcess)
