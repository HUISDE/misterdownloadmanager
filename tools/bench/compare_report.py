"""Statistics for a compare.py run: results.json (for the website) and REPORT.md.

    python tools/bench/compare_report.py C:\\mdm-bench\\results\\<run> [--publish NAME]

Per profile, scenario and client: runs, failures (time-outs, errors, wrong content), and for
the successful runs the median, interquartile range, minimum and maximum of the time, CPU,
memory, connections and requests. Warm-up runs are excluded; failed runs are counted and shown,
never dropped silently. IDM's numbers come from run5 (docs/bench/run5, 2026-10-29) for the four
scenarios both runs share; IDM was not run again.

--publish NAME copies the raw files and the report into docs/bench/NAME and the results into
website/bench/compare.json.
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from compare import ROOT, SCENARIOS  # noqa: E402

ORDER = ["MDM", "IDM", "ABDM", "FDM", "Gopeed", "Prism", "XDM", "aria2", "curl"]
# A run is "busy" when everything else on the machine used more than this many cores on
# average while it lasted (other programs compiling, say); medians are given with and without.
BUSY_CORES = 2.0
METRICS = ["e2e_ms", "startup_ms", "transfer_ms", "finish_ms", "cpu_s", "cpu_avg_cores", "cpu_peak_cores", "peak_mem_mb", "idle_after_mb", "connections",
           "requests", "peak_parallel"]


def describe(x):
    x = np.asarray([v for v in x if v is not None], float)
    if not len(x):
        return None
    q1, med, q3 = np.percentile(x, [25, 50, 75])
    return {"n": int(len(x)), "median": round(float(med), 3), "q1": round(float(q1), 3), "q3": round(float(q3), 3),
            "min": round(float(x.min()), 3), "max": round(float(x.max()), 3)}


def idm_run5():
    """IDM's medians from run5, in this report's units."""
    p = ROOT / "docs" / "bench" / "run5" / "results.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    out = {"date": d["environment"]["date"], "version": d["environment"]["idm_version"], "scenarios": {}}
    for sc in d["scenarios"]:
        st = sc["clients"]["IDM"]["stats"]
        runs = [r for r in d["runs"] if r["scenario"] == sc["id"] and r["client"] == "IDM" and not r["warmup"]]
        e2e = [r["e2e_ms"] for r in runs if r["ok"]]
        cpu = [r["cpu_ms"] / 1000 for r in runs if r["ok"]]
        avg = [r["cpu_ms"] / r["e2e_ms"] for r in runs if r["ok"] and r["e2e_ms"]]
        out["scenarios"][sc["id"]] = {
            "runs": len(runs), "failed": len(runs) - len(e2e), "sha_failed": None,
            "stats": {"e2e_ms": describe(e2e), "cpu_s": describe(cpu), "cpu_avg_cores": describe(avg),
                      "cpu_peak_cores": None, "peak_mem_mb": st.get("peak_ws_mb"), "idle_after_mb": None,
                      "connections": st.get("connections"), "requests": st.get("requests")},
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--publish", default="")
    ap.add_argument("--status", choices=("final", "provisional"), default="final",
                    help="provisional: the website says a run on a quiet machine will replace it")
    a = ap.parse_args()
    run = Path(a.run)
    runs = json.loads((run / "runs.json").read_text(encoding="utf-8"))
    env = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    log = [json.loads(line) for line in (run / "server.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_name = defaultdict(list)
    for e in log:
        by_name[e["path"].rsplit("/", 1)[-1]].append(e)
    for r in runs:
        reqs = [e for n in r["files"] for e in by_name.get(n, []) if e.get("method") == "GET"]
        r["requests"] = len(reqs)
        r["connections"] = len({e["peer"] for e in reqs})
        # The most requests the server was answering at once for this run.
        ev = sorted([(e["t_start_ms"], 1) for e in reqs] + [(e["t_end_ms"], -1) for e in reqs])
        cur = peak = 0
        for _, d in ev:
            cur += d
            peak = max(peak, cur)
        r["peak_parallel"] = peak
        r["bytes_sent"] = sum(e["bytes_sent"] for e in reqs)
        cal = by_name.get("cal-" + r["files"][0], [])
        sent = [e for e in reqs if e["status"] in (200, 206)]
        if r["ok"] and cal and sent and r.get("cal_ms"):
            off = r["cal_ms"] - cal[0]["t_start_ms"]  # server ms -> harness ms
            first = min(e["t_start_ms"] for e in reqs) + off
            last = max(e["t_end_ms"] for e in sent) + off
            r["startup_ms"] = round(first - r["t0_ms"], 1)
            r["transfer_ms"] = round(last - first, 1)
            r["finish_ms"] = round(r["done_ms"] - last, 1)
            # Anything else the server answered meanwhile (another program using it) would
            # share its bandwidth and connection limit: counted, and such runs are marked.
            a0, a1 = r["t0_ms"] - off, r["done_ms"] - off
            mine = set(r["files"])
            r["foreign_requests"] = sum(1 for e in log if e["t_start_ms"] < a1 and e["t_end_ms"] > a0
                                        and e["path"].rsplit("/", 1)[-1] not in mine
                                        and not e["path"].rsplit("/", 1)[-1].startswith("cal-"))

    for c, e in env.get("clients", {}).items():
        if c == "curl" and e["version"].startswith("curl "):
            e["version"] = e["version"].split()[1]
        if c == "aria2":
            e["version"] = e["version"].replace("aria2 version ", "")
    idm = idm_run5()
    out = {"environment": env, "status": a.status, "idm": {"source": "run5", "date": idm["date"], "version": idm["version"]},
           "scenarios": []}
    for profile in ("matched", "defaults"):
        for sid, title, size, nfiles, faults, _, _ in SCENARIOS:
            rs = [r for r in runs if r["scenario"] == sid and r["profile"] == profile and not r["warmup"]]
            if not rs:
                continue
            sc = {"profile": profile, "id": sid, "title": title, "size": size, "files": nfiles,
                  "faults": faults or "none", "clients": {}}
            for c in ORDER:
                cr = [r for r in rs if r["client"] == c]
                if not cr:
                    if c == "IDM" and profile == "matched" and sid in idm["scenarios"]:
                        sc["clients"]["IDM"] = dict(idm["scenarios"][sid], source="run5")
                    continue
                good = [r for r in cr if r["ok"] and r["sha_ok"]]
                quiet = [r for r in good if (r.get("others_avg_cores") or 0) <= BUSY_CORES
                         and not r.get("foreign_requests")]
                sc["clients"][c] = {
                    "busy_runs": len(good) - len(quiet),
                    "e2e_ms_quiet": describe([r["e2e_ms"] for r in quiet]),
                    "others_avg_cores": describe([r.get("others_avg_cores") for r in cr]),
                    "connections_setting": 1 if c == "curl" else cr[0]["connections_setting"],
                    "runs": len(cr),
                    "failed": sum(1 for r in cr if not r["ok"]),
                    "sha_failed": sum(1 for r in cr if r["ok"] and not r["sha_ok"]),
                    "errors": sorted({r["error"] for r in cr if r["error"]}),
                    "stats": {m: describe([r.get(m) for r in good]) for m in METRICS},
                }
            out["scenarios"].append(sc)
    out["runs"] = [{k: r.get(k) for k in ("profile", "scenario", "client", "run", "warmup", "ok", "sha_ok", "error",
                                          "e2e_ms", "startup_ms", "transfer_ms", "finish_ms", "cpu_s", "cpu_avg_cores",
                                          "cpu_peak_cores", "peak_mem_mb", "idle_after_mb", "connections", "requests", "peak_parallel", "connections_setting",
                                          "others_avg_cores", "others_peak_cores", "position", "foreign_requests")}
                   for r in runs]
    (run / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    def cell(s, m, fmt):
        st = s["stats"].get(m) if s else None
        if not st:
            return "—"
        if isinstance(st, (int, float)):
            return fmt(st)
        return fmt(st["median"])

    def secs(v):
        return f"{v / 1000:.2f} s"

    lines = [f"# Download managers compared — {env['date']}", "",
             f"{env['cpu']}, {env['ram_gb']} GB RAM, {env['os']}. {env['server']}. Destination {env['disk']}.", "",
             "| App | Version | Default connections |", "|---|---|---|"]
    for c in ORDER:
        if c in env["clients"]:
            e = env["clients"][c]
            lines.append(f"| {e['label']} | {e['version']} | {e['default_connections']} |")
    lines.append(f"| Internet Download Manager | {idm['version']} (run5, {idm['date'][:10]}, not re-run) | 8 |")
    for sc in out["scenarios"]:
        lines += ["", f"## {sc['title']} — {'8 connections each' if sc['profile'] == 'matched' else 'each app at its defaults'}",
                  "", "| App | Runs ok | Time, median (IQR) | min–max | Quiet runs: median | CPU s | avg / peak cores | Peak MB | Idle after MB | Connections (most at once) | Requests |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for c, s in sc["clients"].items():
            st = s["stats"]["e2e_ms"]
            t = f"{secs(st['median'])} ({secs(st['q1'])}–{secs(st['q3'])})" if st else "—"
            mm = f"{secs(st['min'])}–{secs(st['max'])}" if st else "—"
            okn = s["runs"] - s["failed"] - (s["sha_failed"] or 0)
            note = ""
            if s["failed"]:
                note += f", {s['failed']} failed"
            if s["sha_failed"]:
                note += f", {s['sha_failed']} wrong content"
            src = " (run5)" if s.get("source") == "run5" else ""
            qs = s.get("e2e_ms_quiet")
            quiet = (f"{secs(qs['median'])} (n={qs['n']})" if qs else "—") if s.get("source") != "run5" else "—"
            lines.append(
                f"| {c}{src} | {okn}/{s['runs']}{note} | {t} | {mm} | {quiet} | {cell(s, 'cpu_s', lambda v: f'{v:.2f}')} | "
                f"{cell(s, 'cpu_avg_cores', lambda v: f'{v:.2f}')} / {cell(s, 'cpu_peak_cores', lambda v: f'{v:.2f}')} | "
                f"{cell(s, 'peak_mem_mb', lambda v: f'{v:.0f}')} | {cell(s, 'idle_after_mb', lambda v: f'{v:.0f}')} | "
                f"{cell(s, 'connections', lambda v: f'{v:.0f}')} ({cell(s, 'peak_parallel', lambda v: f'{v:.0f}')}) | "
                f"{cell(s, 'requests', lambda v: f'{v:.0f}')} |")
    errs = sorted({(r["client"], r["scenario"], r["error"]) for r in runs if r["error"] and not r["warmup"]})
    if errs:
        lines += ["", "## Failures", ""] + [f"- {c}, {s}: {e}" for c, s, e in errs]
    (run / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    if a.publish:
        docs = ROOT / "docs" / "bench" / a.publish
        docs.mkdir(parents=True, exist_ok=True)
        for f in ("results.json", "REPORT.md", "environment.json", "runs.json", "server.jsonl", "restored.json"):
            if (run / f).exists():
                shutil.copy(run / f, docs / f)
        site = ROOT / "website" / "bench"
        site.mkdir(parents=True, exist_ok=True)
        shutil.copy(run / "results.json", site / "compare.json")
        print(f"published to {docs} and {site / 'compare.json'}")


if __name__ == "__main__":
    main()
