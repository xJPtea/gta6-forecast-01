# GTA VI Twitch Forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/xJPtea/gta6-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/xJPtea/gta6-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)


## What it does

`main.py` (Python 3.13, standard library only, no network, deterministic) reads one case file from `/input/<id>.in` and writes `/output/<id>.out`: for each of hours 2–24 of the release day, five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent Twitch viewers in the Grand Theft Auto VI category.

Method: log-scale analog forecaster. For each comparable past launch it takes the release-day log-ratio curve ln(v_h / v_1), corrects each curve's level to the case's own hour-1 print with a robust Theil–Sen slope, then reads weighted quantiles off the corrected curves (console-only launches weighted ×3.5, rolling-midnight ×1.3, simultaneous global PC ×0.35, plus recency and a Gaussian kernel on log hour-1 distance), with spread floors and a structural floor on the late-day peak (the Americas unlock at hours 6 and 9, so a rolling launch's peak must exceed hour 1).

## Local validation

Scored on the four practice cases with the exact pinball loss from the rules (see `score_local.py`; answers fetched from SullyGnome's "Average viewers" series per the kit's NOTICE.txt):

| case | our loss | baseline loss |
|---|---|---|
| p00 Marvel's Wolverine | 0.3745 | 0.7437 |
| p01 Red Dead Redemption 2 | 0.2028 | 0.2868 |
| p02 God of War Ragnarök | 0.1182 | 0.2146 |
| p03 Marvel's Spider-Man 2 | 0.1659 | 0.3033 |
| **mean** | **0.2154** | **0.3871** |

Leave-one-out mean loss 0.2237. See `DOSSIER.md` for method, parameters, and honest limitations.

## Run locally

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```
