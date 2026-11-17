"""Local scorer for the GTA VI forecaster (practice cases only).

Runs main.py (and the kit starter, the house baseline) on the four
practice cases in the kit, then scores every forecast against the
answers fetched from SullyGnome's "Average viewers" series
(answers_practice.json; hour 1 of each matches the case's known print
exactly, which verifies the series).

Pinball loss per the rules: for each scored hour h (2..24) and level
tau, d = ln(y) - ln(q), loss = 2 * max(tau*d, (tau-1)*d); the loss is
the mean over all items. Typical miss = 100 * (exp(m) - 1) where m is
the mean |ln(y) - ln(median)|. 90% coverage = share of scored hours
with q05 <= y <= q95.

Usage: python3 score_local.py [--main main.py] [--outdir DIR]
Prints a per-case table and the mean loss for both entries.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = Path(os.environ.get("GTA6_KIT", str(Path.home() / "workspace/makefun/gta6-forecast-01-kit")))
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


def pinball(y, q, tau):
    d = math.log(max(1.0, y)) - math.log(max(1.0, q))
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def score_case(forecast, answers):
    """forecast: {"hours": [...]}, answers: {hour_str: viewers}."""
    rows = {r["hour"]: r["q"] for r in forecast["hours"]}
    total = 0.0
    n = 0
    abs_log = []
    covered = 0
    scored_hours = 0
    for h in range(2, 25):
        y = answers.get(str(h))
        if y is None or h not in rows:
            continue
        q = rows[h]
        for tau, qv in zip(LEVELS, q):
            total += pinball(y, qv, tau)
            n += 1
        abs_log.append(abs(math.log(max(1.0, y)) - math.log(max(1.0, q[2]))))
        if q[0] <= y <= q[4]:
            covered += 1
        scored_hours += 1
    if n == 0:
        return None
    loss = total / n
    typical_miss = 100.0 * (math.exp(sum(abs_log) / len(abs_log)) - 1.0)
    coverage = covered / scored_hours if scored_hours else 0.0
    return {"loss": loss, "typical_miss_pct": typical_miss,
            "coverage90": coverage, "hours": scored_hours}


def validate_output(forecast, stem):
    problems = []
    if set(forecast.keys()) != {"hours"}:
        problems.append(f"{stem}: keys {sorted(forecast.keys())} != ['hours']")
    rows = forecast.get("hours", [])
    if len(rows) != 23:
        problems.append(f"{stem}: {len(rows)} rows, want 23")
    seen = set()
    for r in rows:
        if set(r.keys()) != {"hour", "q"}:
            problems.append(f"{stem}: row keys {sorted(r.keys())}")
        h = r.get("hour")
        if h in seen:
            problems.append(f"{stem}: duplicate hour {h}")
        seen.add(h)
        q = r.get("q", [])
        if len(q) != 5:
            problems.append(f"{stem} h{h}: {len(q)} quantiles, want 5")
            continue
        for v in q:
            if not (isinstance(v, (int, float)) and math.isfinite(v)
                    and 0 < v <= 1e9):
                problems.append(f"{stem} h{h}: bad quantile {v!r}")
        if any(q[i] > q[i + 1] for i in range(4)):
            problems.append(f"{stem} h{h}: quantiles decrease {q}")
    if seen != set(range(2, 25)):
        problems.append(f"{stem}: hours {sorted(seen)} != 2..24")
    return problems


def run_entry(script, input_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.out"):
        old.unlink()
    env = dict(os.environ)
    env["MAKEFUN_INPUT_DIR"] = str(input_dir)
    env["MAKEFUN_OUTPUT_DIR"] = str(out_dir)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(script)], env=env,
        capture_output=True, text=True, timeout=120)
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"{script} exited {proc.returncode}")
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(HERE / "main.py"))
    ap.add_argument("--starter", default=str(KIT / "starter/main.py"))
    ap.add_argument("--input", default=str(KIT / "input"))
    ap.add_argument("--answers", default=str(HERE / "answers_practice.json"))
    ap.add_argument("--outdir", default=str(HERE / "out"))
    args = ap.parse_args()

    answers = json.loads(Path(args.answers).read_text())
    input_dir = Path(args.input)
    out_base = Path(args.outdir)

    results = {}
    for label, script in (("ours", args.main), ("baseline", args.starter)):
        out_dir = out_base / label
        dt = run_entry(script, input_dir, out_dir)
        per_case = {}
        problems = []
        for pid in sorted(answers):
            out_path = out_dir / f"{pid}.out"
            if not out_path.exists():
                problems.append(f"{pid}: no output file")
                continue
            raw = out_path.read_bytes()
            if len(raw) > 65536:
                problems.append(f"{pid}: output {len(raw)} bytes > 65536")
            forecast = json.loads(raw)
            problems += validate_output(forecast, pid)
            per_case[pid] = score_case(forecast, answers[pid]["hours"])
        results[label] = {"per_case": per_case, "seconds": dt,
                          "problems": problems}

    print(f"{'case':4s} {'game':28s} {'ours loss':>10s} {'base loss':>10s} "
          f"{'ours miss%':>10s} {'base miss%':>10s} {'ours cov':>8s} {'base cov':>8s}")
    for pid in sorted(answers):
        o = results["ours"]["per_case"].get(pid)
        b = results["baseline"]["per_case"].get(pid)
        name = answers[pid]["game"][:28]
        print(f"{pid:4s} {name:28s} "
              f"{o['loss']:10.6f} {b['loss']:10.6f} "
              f"{o['typical_miss_pct']:10.1f} {b['typical_miss_pct']:10.1f} "
              f"{o['coverage90']:8.2f} {b['coverage90']:8.2f}")
    for label in ("ours", "baseline"):
        losses = [c["loss"] for c in results[label]["per_case"].values()]
        miss = [c["typical_miss_pct"] for c in results[label]["per_case"].values()]
        cov = [c["coverage90"] for c in results[label]["per_case"].values()]
        print(f"{label}: mean loss {sum(losses)/len(losses):.6f} | "
              f"mean typical miss {sum(miss)/len(miss):.1f}% | "
              f"mean coverage90 {sum(cov)/len(cov):.2f} | "
              f"runtime {results[label]['seconds']:.2f}s for 4 cases")
        for p in results[label]["problems"]:
            print(f"  PROBLEM [{label}]: {p}")
    print("baseline target from RULES: loss ~0.387, typical miss ~82.8%, "
          "coverage ~0.783")


if __name__ == "__main__":
    main()
