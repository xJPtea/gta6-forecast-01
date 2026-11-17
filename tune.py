"""Grid-search tuner for main.py's CONFIG on the practice cases.

Evaluates every config in-process (import main, call forecast_case)
and scores with the same pinball loss as score_local.py. Then runs
leave-one-out: for each held-out case, the best config is chosen on
the other three cases only, and the held-out case is scored with it.
That LOO number is the honest generalisation estimate; the
tuned-on-all-four number is optimistic by construction.

Usage: python3 tune.py
"""

import itertools
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = Path.home() / "workspace/makefun/gta6-forecast-01-kit"
sys.path.insert(0, str(HERE))

import main as M  # noqa: E402

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


def pinball(y, q, tau):
    d = math.log(max(1.0, y)) - math.log(max(1.0, q))
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def score(forecast, answers):
    rows = {r["hour"]: r["q"] for r in forecast["hours"]}
    total, n = 0.0, 0
    covered, hours = 0, 0
    for h in range(2, 25):
        y = answers.get(str(h))
        if y is None or h not in rows:
            continue
        q = rows[h]
        for tau, qv in zip(LEVELS, q):
            total += pinball(y, qv, tau)
            n += 1
        if q[0] <= y <= q[4]:
            covered += 1
        hours += 1
    return {"loss": total / n, "coverage": covered / hours}


def load_cases():
    answers = json.loads((HERE / "answers_practice.json").read_text())
    cases = {}
    for pid in sorted(answers):
        cases[pid] = (
            json.loads((KIT / "input" / f"{pid}.in").read_text()),
            answers[pid]["hours"])
    return cases


def eval_config(cfg, cases, pids):
    per = {}
    for pid in pids:
        case, ans = cases[pid]
        per[pid] = score(M.forecast_case(case, cfg), ans)
    mean_loss = sum(v["loss"] for v in per.values()) / len(per)
    return mean_loss, per


def main():
    cases = load_cases()
    pids = sorted(cases)

    grid = {
        "slope_cap": [0.0, 0.3, 0.6],
        "level_bandwidth": [0.8, 1.2, 2.0],
        "console_weight": [1.0, 1.6, 2.5],
        "global_weight": [0.2, 0.35],
        "spread_mult": [1.0, 1.15, 1.3],
        "smooth_median": [0, 1],
    }
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"grid: {len(combos)} configs x {len(pids)} cases")

    best = []
    for combo in combos:
        cfg = dict(M.CONFIG)
        cfg.update(dict(zip(keys, combo)))
        mean_loss, per = eval_config(cfg, cases, pids)
        best.append((mean_loss, dict(zip(keys, combo)), per))
    best.sort(key=lambda t: t[0])
    print("\ntop 8 configs (tuned on all 4 cases):")
    for mean_loss, cfg, per in best[:8]:
        detail = " ".join(f"{pid}={per[pid]['loss']:.4f}" for pid in pids)
        print(f"  loss {mean_loss:.6f} | {cfg} | {detail}")

    # Leave-one-out: choose the config on 3 cases, score the 4th.
    print("\nleave-one-out (config chosen on the other 3 cases):")
    loo_losses = {}
    for held in pids:
        train = [p for p in pids if p != held]
        scored = []
        for combo in combos:
            cfg = dict(M.CONFIG)
            cfg.update(dict(zip(keys, combo)))
            mean_loss, _ = eval_config(cfg, cases, train)
            scored.append((mean_loss, cfg))
        scored.sort(key=lambda t: t[0])
        best_cfg = scored[0][1]
        held_mean, held_per = eval_config(best_cfg, cases, [held])
        loo_losses[held] = held_per[held]["loss"]
        print(f"  held {held}: loss {held_per[held]['loss']:.6f} "
              f"with {best_cfg}")
    print(f"LOO mean loss: {sum(loo_losses.values())/len(loo_losses):.6f} "
          f"(baseline 0.387097)")

    # Also report the single best-on-all-4 config's per-case coverage.
    best_cfg = dict(M.CONFIG)
    best_cfg.update(best[0][1])
    _, per = eval_config(best_cfg, cases, pids)
    print("\nbest config per-case coverage:",
          {pid: round(per[pid]['coverage'], 2) for pid in pids})
    print("best config:", best[0][1])


if __name__ == "__main__":
    main()
