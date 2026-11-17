# DOSSIER — gta6-twitch-ccu-forecast-01 entry

Entry: log-scale analog forecaster. Single file `main.py` (Python 3.13,
standard library only, no network, deterministic). Built 17 Nov 2026,
session started after the competition opened (17 Nov 06:00 UTC).

## Method

A launch day's Twitch curve is driven by the rolling midnight unlock:
hour 1 (00:00–01:00 UTC) covers only the timezones already past
midnight, so viewership dips in hours 2–4, bumps when Europe wakes and
the US East unlocks (hours 5–7), dips midday, then climbs into US prime
time (hours 17–22). How far it climbs depends strongly on how big hour 1
already is: launches whose hour 1 is already near peak (a simultaneous
global PC unlock) stay flat, while console-only rolling launches with a
small hour 1 grow several-fold.

For each comparable launch in the case, take its release-day log-ratio
curve ln(v_h / v_1), hours 2–24 (missing hours interpolated in log
space). Then, per hour:

1. **Level correction.** Within the rolling/console pool, the log-ratio
   falls as hour-1 level rises. Fit a weighted Theil–Sen slope of
   log-ratio on log hour-1 (robust: one niche launch with an extreme
   ratio must not set the slope), capped at ±0.6, and shift every
   comparable's curve to the case's own hour-1 level (shift capped at
   ±0.7 log units). Fitted late-hour slopes are about −0.2 to −0.35;
   early-hour slopes are near 0 (the dip is level-independent).
2. **Weighted quantiles.** Weights: console-only ×3.5, rolling-midnight
   ×1.3, simultaneous-global-PC ×0.35, recency ×(1 − 0.03 × years since
   2026, floor 0.75), and a Gaussian kernel on log hour-1 distance
   (bandwidth 1.2). Read the five quantiles off the weighted
   distribution of the corrected curves.
3. **Spread floors.** Each side keeps its empirical width or a floor,
   whichever is wider (90% half-spread ≥ 0.30 log units, 50% ≥ 0.12),
   times spread multiplier 1.0, so the forecast never claims more
   precision than 38 noisy analogs justify.
4. **Structural floor.** The Americas unlock at hours 6 and 9, so a
   rolling launch's peak after hour 6 must exceed hour 1. The median
   curve's late-day peak is floored at the smallest peak ratio among
   this case's own console-only comparables (clamped to [1.15, 1.5];
   in practice 1.34, from The Last of Us Part II). This stops the level
   correction from extrapolating the flat global-PC regime into a
   declining day at a very large hour 1.
5. **Streams (final case only).** If the top live stream alone is more
   than 40% of hour-1 viewers, widen the spread by up to 30%: a
   concentrated category is less predictable. Streams are null in the
   practice cases, so this never fires there. `categories_hourly` is
   read but not used for the median (no practice data to validate any
   use of it).
6. **Excluded:** the Grand Theft Auto VI pre-release-history comparable
   ("Not a launch", day_start 2026-08-27) is not a launch curve and is
   left out of the analog pool.

Output: `{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}]}`,
23 rows, hours 2–24, quantiles non-decreasing, each in (0, 1e9],
rounded half-up to 2 decimals, one key only, ~1.5 KB per file.

## Final parameters (main.py CONFIG)

console_weight 3.5, rolling_weight 1.3, global_weight 0.35,
recency_slope 0.03 / floor 0.75, level_bandwidth 1.2, slope_cap 0.6,
shift_cap 0.7, spread_mult 1.0, min_half_spread_90 0.30,
min_half_spread_50 0.12, smooth_median 0 (off: the dips/bumps are real),
stream_share_threshold 0.40, stream_share_max_extra 0.30.

Chosen by a 324-config grid search on the practice cases, then
sanity-checked for robustness: the top-8 configs sit within 0.003 of
each other, so the surface is flat and the choice is not a knife-edge.
Console weight 3.5 over 2.5 was kept because it improves 3 of 4 cases
and matches the prior (GTA VI is console-only); weight 5.0+ was
rejected — it starts degrading the small-hour-1 case and rests the
forecast on ~12 curves only.

## Local validation (score_local.py)

Answers fetched from SullyGnome's "Average viewers" series (NOTICE.txt
endpoint), one request per practice game, release month only, viewers
only — 4 requests total. Hour 1 of the fetched series matches each
case's `known` print exactly (23,357 / 116,550 / 269,517 / 119,087),
which verifies the series and the scorer. Pinball loss exactly per
RULES: 2·max(τ·d, (τ−1)·d), d = ln(y) − ln(q).

| case | game | our loss | baseline loss | our miss | base miss | our cov90 | base cov90 |
|---|---|---|---|---|---|---|---|
| p00 | Marvel's Wolverine | 0.3745 | 0.7437 | 82.8% | 188.8% | 0.83 | 0.52 |
| p01 | Red Dead Redemption 2 | 0.2028 | 0.2868 | 42.8% | 65.4% | 0.70 | 0.91 |
| p02 | God of War Ragnarök | 0.1182 | 0.2146 | 20.5% | 42.0% | 0.96 | 0.87 |
| p03 | Marvel's Spider-Man 2 | 0.1659 | 0.3033 | 27.3% | 64.4% | 0.91 | 0.83 |
| **mean** | | **0.2154** | **0.3871** | **43.3%** | **90.2%** | **0.85** | **0.78** |

Baseline reproduced by running the kit starter: 0.387097 vs the RULES'
"about 0.387" (coverage 0.78 vs 0.783) — the scorer is validated
against the house's own numbers.

- **Mean loss 0.2154 vs baseline 0.3871: 44% better.**
- **Leave-one-out mean loss 0.2237** (tune.py: for each held-out case
  the config is re-chosen on the other three only, then the held-out
  case is scored). This is the honest generalisation estimate; the
  tuned-on-all-four number is optimistic by construction.
- Coverage 0.85 mean vs the honest 0.90 target: intervals are a touch
  narrow on some cases (p01 0.70), a touch wide on others (p02 0.96).
- Runtime: ~0.06 s per case (0.23–0.29 s for all four), limit 8 s.
  Two runs produce byte-identical outputs. Output ~1.5 KB, limit
  65,536 bytes. Format validated: 23 rows, hours 2–24, monotone
  quantiles, all in range.
- Final-case behaviour (synthetic h00, p1 = 600,000, top stream 50%
  of hour 1): peak median ratio 1.34 at hour 19 (the structural
  floor), spread wider with streams than without (log q95/q05 1.26
  vs 1.17). Peak median ratio vs hour-1 level: 50k → 2.55, 117k →
  1.82, 300k → 1.39, 600k+ → 1.34 (floor). A tiny hour-1 edge case
  (5 viewers) runs cleanly and stays inside the observed analog range.

## Honest limitations and risks

- **Only four practice cases.** Every tuning decision rests on four
  launches. LOO (0.224) is the number to trust, not the tuned 0.215.
- **The final is out of range.** No console comparable has hour 1
  above 365k; GTA VI's hour 1 could be 500k–1M+. The floor guards the
  median against a nonsense declining day, but the true shape at that
  scale is unobserved — the peak ratio could plausibly be 1.3x or 2x,
  and the model cannot tell which from the pool alone.
- **Wolverine is the weak case (0.374).** Its 9.09x growth is an
  outlier among console launches; the model under-predicts it badly
  late in the day. If GTA VI behaves like Wolverine (small hour 1
  relative to its eventual audience), expect a similar under-prediction.
- **The house AI model is an invisible bar.** A prize needs a loss
  strictly below the lower of the house baseline and the house model
  forecast (superbot, reasoning max). Beating the baseline by 44% on
  practice says nothing about beating the house model on the final.
- **Practice ≠ final measure.** Practice is graded on SullyGnome
  hourly averages; the final on minute-mean prints. Close, not the
  same. The final also gives minute history, top-20 streams and
  categories_hourly, of which only streams are used (modestly).
- **The GTA VI pre-release hype level is unused.** The category's own
  Aug–Nov history is in the case but carries no launch-day shape, so
  the entry does not use it as a signal.

## Files in ~/workspace/makefun/gta6-build

- `main.py` — the entry (single file, stdlib only).
- `score_local.py` — runs main.py + starter on the practice cases,
  scores pinball loss / typical miss / coverage, validates format.
- `tune.py` — 324-config grid search + leave-one-out.
- `answers_practice.json` — SullyGnome "Average viewers" hours 1–24
  for the four practice launches (hour 1 verified against each case).
- `DOSSIER.md` — this file.
- `out/` — local run outputs (ours + baseline).

## Not done (parent's job)

No GitHub repo created, nothing pushed, nothing submitted. The entry
still needs: repo + transcripts bundle + `makefun check` + submit
before the deadline (19 Nov 2026 01:00 UTC / 08:00 WIB).
