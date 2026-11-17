"""gta6-twitch-ccu-forecast-01 entry: log-scale analog forecaster.

Method (one paragraph): a launch day's Twitch curve is driven by the
rolling midnight unlock: hour 1 (00:00-01:00 UTC) only covers the
timezones already past midnight, so viewership dips in hours 2-4, bumps
when Europe wakes and the US East unlocks (hours 5-7), dips midday, then
climbs into US prime time (hours 17-22). The size of that climb depends
strongly on how big hour 1 already is: launches whose hour 1 is already
near their peak (a simultaneous global PC unlock) stay flat, while
console-only rolling launches with a small hour 1 grow several-fold.
So for each comparable launch in the case we take its release-day
log-ratio curve ln(v_h / v_1), shift every curve to the case's own
hour-1 level with a per-hour local-linear (level) correction, weight
comparables by launch-type similarity and hour-1 closeness, and read
the five forecast quantiles off the weighted distribution of the
corrected curves. Spreads are widened to a floor so the forecast never
claims more precision than 38 noisy analogs justify.

Standard library only, no network, deterministic: no randomness, no
wall-clock reads, iteration in fixed order.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a
# module shipped beside this file would import. (This entry is one file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels.
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Tunable knobs, chosen on the four practice cases (see DOSSIER.md).
# tune.py overrides CONFIG entries while grid-searching; main.py itself
# always runs with the values below.
CONFIG = {
    # Weight of a console-only comparable (GTA VI is console-only).
    "console_weight": 3.5,
    # Weight of a rolling-midnight-unlock comparable.
    "rolling_weight": 1.3,
    # Weight of a simultaneous-global-PC-unlock comparable (different
    # shape: hour 1 already near peak). Downweighted, not dropped:
    # they still say something about the day's ceiling.
    "global_weight": 0.35,
    # Recency: weight = 1 - recency_slope * (2026 - year), floored.
    "recency_slope": 0.03,
    "recency_floor": 0.75,
    # Gaussian kernel bandwidth (log units) for hour-1 level similarity.
    "level_bandwidth": 1.2,
    # Per-hour level-correction slope cap (log-ratio per log-level) and
    # per-comparable shift cap (log units).
    "slope_cap": 0.6,
    "shift_cap": 0.7,
    # Spread multiplier applied around the median, and minimum log
    # half-spreads for the 90% and 50% bands.
    "spread_mult": 1.0,
    "min_half_spread_90": 0.30,
    "min_half_spread_50": 0.12,
    # 3-point smoothing of the median log-ratio curve (0.25/0.5/0.25).
    # 1 = on, 0 = off. Off: the dips and bumps are real signal.
    "smooth_median": 0,
    # Streams-concentration spread widening (final case only; streams
    # are null in practice). If the top live stream alone is more than
    # this share of hour 1's viewers, widen the spread.
    "stream_share_threshold": 0.40,
    "stream_share_max_extra": 0.30,
}


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, like the starter's round2."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def weighted_quantile(pairs, level):
    """Weighted quantile of [(value, weight)] at `level` in (0, 1).

    Linear interpolation on the cumulative weight axis; deterministic.
    """
    pts = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in pts)
    if total <= 0:
        raise ValueError("weighted_quantile with no weight")
    target = level * total
    acc = 0.0
    prev_v, prev_c = pts[0][0], 0.0
    for v, w in pts:
        acc += w
        if acc >= target:
            if acc == w:  # first point reaches the target alone
                return v
            # Interpolate between the previous point and this one.
            frac = (target - prev_c) / (acc - prev_c) if acc > prev_c else 0.0
            return prev_v + frac * (v - prev_v)
        prev_v, prev_c = v, acc
    return pts[-1][0]


def weighted_median(pairs):
    """Weighted median of [(value, weight)]."""
    return weighted_quantile(pairs, 0.5)


def theil_sen_slope(points, cap):
    """Robust slope of y on x for [(y, weight, x)].

    Weighted median of the pairwise slopes (Theil-Sen): unlike least
    squares it is not dragged by one niche launch with an extreme
    ratio, which matters because the slope is extrapolated to hour-1
    levels outside the pool's range. Capped to [-cap, cap].
    """
    slopes = []
    n = len(points)
    for i in range(n):
        yi, wi, xi = points[i]
        for j in range(i + 1, n):
            yj, wj, xj = points[j]
            dx = xj - xi
            if abs(dx) > 0.1:
                slopes.append(((yj - yi) / dx, wi * wj))
    if not slopes:
        return 0.0
    slope = weighted_median(slopes)
    return max(-cap, min(cap, slope))


def release_day_curve(comp):
    """Release-day hourly viewers (hours 1..24) of one comparable.

    Returns a list of 24 floats or None when hour 1 is missing/zero.
    Missing interior hours are interpolated linearly in log space
    between the nearest known hours of the release day; a missing
    edge hour (other than hour 1) is filled from its nearest known
    neighbour. Hours are SullyGnome points, one per hour at most.
    """
    day_start = parse_time(comp["day_start"])
    by_hour = {}
    for p in comp.get("hourly", []):
        try:
            viewers = float(p["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        if viewers <= 0:
            continue
        t = parse_time(p["from"])
        offset = (t - day_start).total_seconds() / 3600.0
        if offset == int(offset) and 0 <= int(offset) < 24:
            by_hour[int(offset)] = viewers
    if 0 not in by_hour:
        return None
    known = sorted(by_hour)
    curve = []
    for h in range(24):
        if h in by_hour:
            curve.append(by_hour[h])
            continue
        before = [k for k in known if k < h]
        after = [k for k in known if k > h]
        if before and after:
            lo, hi = before[-1], after[0]
            frac = (h - lo) / (hi - lo)
            curve.append(math.exp(
                math.log(by_hour[lo]) * (1 - frac) + math.log(by_hour[hi]) * frac))
        elif before:
            curve.append(by_hour[before[-1]])
        elif after:
            curve.append(by_hour[after[0]])
        else:  # pragma: no cover - unreachable when hour 1 exists
            curve.append(by_hour[0])
    return curve


def comparable_features(comp):
    """Launch-type features used for weighting, from the case text."""
    platforms = comp.get("platforms", "") or ""
    unlock = comp.get("unlock", "") or ""
    unlock_l = unlock.lower()
    console_only = "PC" not in platforms
    global_pc = ("PC" in platforms) and (
        "global" in unlock_l or "simultaneous" in unlock_l
        or "single global" in unlock_l)
    rolling = ("rolling" in unlock_l) or ("midnight local" in unlock_l)
    try:
        year = parse_time(comp["day_start"]).year
    except (KeyError, TypeError, ValueError):
        year = 2023
    # The target's own pre-release history is not a launch curve.
    target_history = ("not a launch" in unlock_l
                      or "target-history" in unlock_l
                      or "before release" in comp.get("name", "").lower())
    return {
        "console_only": console_only,
        "global_pc": global_pc,
        "rolling": rolling,
        "year": year,
        "target_history": target_history,
    }


def comparable_weight(feat, log_p1_comp, log_p1_case, cfg):
    """Similarity weight of one comparable for the case at hand."""
    w = 1.0
    if feat["console_only"]:
        w *= cfg["console_weight"]
    if feat["rolling"]:
        w *= cfg["rolling_weight"]
    if feat["global_pc"]:
        w *= cfg["global_weight"]
    year_gap = max(0, 2026 - feat["year"])
    w *= max(cfg["recency_floor"], 1.0 - cfg["recency_slope"] * year_gap)
    bw = cfg["level_bandwidth"]
    w *= math.exp(-0.5 * ((log_p1_comp - log_p1_case) / bw) ** 2)
    return w


def forecast_case(case, cfg=None):
    """Forecast one case: {"hours": [{"hour": h, "q": [...]} x 23]}."""
    cfg = dict(CONFIG if cfg is None else cfg)
    if case["levels"] != LEVELS:
        raise ValueError(f"levels {case['levels']}, not {LEVELS}")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    log_p1 = math.log(p1)

    # Build the analog pool: per comparable, its release-day log-ratio
    # curve ln(v_h / v_1), hours 2..24, plus its weight.
    pool = []  # (weight, feat, log_p1_comp, [log-ratio h=2..24])
    for comp in case.get("comparables", []):
        feat = comparable_features(comp)
        if feat["target_history"]:
            continue
        curve = release_day_curve(comp)
        if curve is None:
            continue
        log_ratios = [math.log(curve[h] / curve[0]) for h in range(1, 24)]
        w = comparable_weight(feat, math.log(curve[0]), log_p1, cfg)
        pool.append((w, feat, math.log(curve[0]), log_ratios))
    if not pool:
        raise ValueError("no usable comparables")

    # Per-hour level correction: within the rolling/console pool the
    # log-ratio falls as hour-1 level rises. Fit a weighted slope of
    # log-ratio on log hour-1 per hour, shrink it to [-cap, cap], and
    # shift every comparable's curve to the case's own level before
    # taking quantiles. The shift per comparable is capped too, so a
    # far-away level can never drag a curve by more than 0.7 log units.
    hours_out = []
    medians = []
    spreads = []  # (q05, q25, q75, q95) offsets from the median, log units
    for hi in range(23):  # hi 0..22 -> hour hi+2
        hour = hi + 2
        # Slope fit on rolling or console-only comparables only: the
        # global-PC regime has a different (flat) shape and would
        # flatten the slope toward zero. Theil-Sen, not least squares:
        # one niche launch with an extreme ratio must not set the
        # slope that gets extrapolated to the case's level.
        fit_pts = [(lr[hi], w, lp1) for (w, f, lp1, lr) in pool
                   if f["rolling"] or f["console_only"]]
        slope = 0.0
        if len(fit_pts) >= 5:
            slope = theil_sen_slope(fit_pts, cfg["slope_cap"])
        shifted = []
        for w, _f, lp1, lr in pool:
            shift = -slope * (lp1 - log_p1)
            shift = max(-cfg["shift_cap"], min(cfg["shift_cap"], shift))
            shifted.append((lr[hi] + shift, w))
        q = [weighted_quantile(shifted, lv) for lv in LEVELS]
        medians.append(q[2])
        spreads.append((q[0] - q[2], q[1] - q[2], q[3] - q[2], q[4] - q[2]))
        hours_out.append(hour)

    # Light 3-point smoothing of the median curve only; spreads keep
    # their per-hour honest width.
    if cfg["smooth_median"]:
        sm = []
        for i, m in enumerate(medians):
            lo = medians[i - 1] if i > 0 else m
            hi = medians[i + 1] if i < len(medians) - 1 else m
            sm.append(0.25 * lo + 0.5 * m + 0.25 * hi)
        medians = sm

    # Structural floor (rolling unlock): the Americas unlock at hours
    # 6 and 9, so a rolling launch's peak after hour 6 must exceed
    # hour 1. The floor is the smallest peak ratio among this case's
    # own console-only comparables, clamped to [1.15, 1.5]. Without
    # it the level correction extrapolates the flat global-PC regime
    # and can predict a declining day at a very large hour 1.
    console_peaks = [max(lr) for (_w, f, _lp1, lr) in pool
                     if f["console_only"]]
    if console_peaks:
        floor_ratio = min(1.5, max(1.15, math.exp(min(console_peaks))))
        floor_log = math.log(floor_ratio)
        late_max = max(m for h, m in zip(hours_out, medians) if h >= 6)
        if late_max < floor_log:
            lift = floor_log - late_max
            medians = [m + lift if h >= 6 else m
                       for h, m in zip(hours_out, medians)]

    # Streams concentration (final case only): if one live stream
    # dominates hour 1, the category is concentrated and the day is
    # less predictable, so widen the spread. Streams are null in the
    # practice cases, so this never fires there.
    extra_spread = 1.0
    streams = case.get("streams")
    if streams:
        try:
            top = max(float(s.get("viewers", 0) or 0) for s in streams)
            share = top / p1 if p1 > 0 else 0.0
            if share > cfg["stream_share_threshold"]:
                extra = min(cfg["stream_share_max_extra"],
                            0.75 * (share - cfg["stream_share_threshold"]))
                extra_spread = 1.0 + extra
        except (TypeError, ValueError):
            pass

    rows = []
    for i, hour in enumerate(hours_out):
        med = medians[i]
        q05o, q25o, q75o, q95o = spreads[i]
        # Widen around the median; each side keeps its empirical width
        # or the floor, whichever is wider. Offsets are ordered by
        # construction (q05 <= q25 <= median <= q75 <= q95).
        sm = cfg["spread_mult"] * extra_spread
        lo90 = max(-q05o, cfg["min_half_spread_90"]) * sm
        lo50 = max(-q25o, cfg["min_half_spread_50"]) * sm
        hi50 = max(q75o, cfg["min_half_spread_50"]) * sm
        hi90 = max(q95o, cfg["min_half_spread_90"]) * sm
        log_q = [med - lo90, med - lo50, med, med + hi50, med + hi90]
        vals = []
        prev = 0.0
        for lq in log_q:
            v = p1 * math.exp(lq)
            v = min(1e9, max(1.0, v))
            v = round2(v)
            v = max(v, prev)  # non-decreasing within the row
            vals.append(v)
            prev = v
        rows.append({"hour": hour, "q": vals})
    return {"hours": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
