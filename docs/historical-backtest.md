# Historical replay of the saved weekly cohort

The local replay uses the 25 symbols saved in the published `testing-results.json`.
It does not write to the website, forecast ledger, or weekly testing records.

The requested two calendar months, August 19–October 19, 2026, contain 43 market
sessions and therefore 1,075 possible stock/session comparisons. October 13 is
included for every stock.

## Timing and training

- Reconstruct each morning's inputs before 6 AM America/Los_Angeles.
- Use that date's preceding 365 calendar days of completed training outcomes.
- Every training row's features use its own preceding 365 days of prices; older
  raw history is necessary to construct those historical features.
- Preserve the existing mixture of morning and next-session intraday examples.
  Intraday examples use the preceding 90 calendar days, matching the existing
  collector's window at each replay date.
- Model settings, feature variant, and nonnegative ensemble weights are selected
  before each 10-session block, using only earlier chronological validation folds.
  Selected estimators are refitted daily. This is an explicit replay schedule;
  it does not rerun hyperparameter selection every morning.
- Target-day and future prices are removed before building prediction inputs.
  Target-day labels are excluded from model selection, training, and calibration.
- Freeze each day's predictions to a separate JSON file before comparing with
  target-day opening and closing prices.

Historical news snapshots are not archived, so this replay uses the supported
price-only variants. It does not substitute today's headlines. Bars downloaded
today can reflect later corrections and split adjustments. Consequently this is
a reconstructed historical test, not an exact reproduction of forecasts actually
saved on those dates. The cohort was selected after the start of the test period,
and the new algorithms were also developed afterward; these results are research
on that fixed cohort, not a live forward test or universe-selection backtest.

## Commands

Download raw historical data, retaining source URLs and timestamps:

```sh
node scripts/backtest-data.mjs work/backtest-2026-08-19_2026-10-19
```

Run the historical replay locally:

```sh
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 python3 scripts/historical-backtest.py \
  --input work/backtest-2026-08-19_2026-10-19 \
  --output work/backtest-2026-08-19_2026-10-19/results
```

The output folder contains `results.csv`, `results.json`, `report.md`, per-day
frozen prediction files, and each block's selection diagnostics. `manifest.json`
fingerprints the inputs, model source, and parameters. Interrupted runs with
unchanged inputs can reuse their completed selection and prediction files.
Changed inputs or source require a new output directory. `work/` is ignored by Git.

Validate leakage boundaries, actual-return calculation, and replay resumption:

```sh
python3 -m unittest discover -s scripts -p historical_backtest_test.py
```

## Completed local run

All 1,075 comparisons completed for 43 sessions and the saved 25 symbols.
Direction accuracy was 511/1,075 (47.53%). MAE was 2.7429 percentage points,
versus 2.7326 for always predicting zero and 2.7324 for the training-median baseline.
The historical-median direction baseline achieved 51.81%. This replay did not
show an improvement over these simple baselines. It is not a same-period v7/v8
comparison; Monday's earlier 56% result covered only one day.

Average absolute prediction was 0.2964%, versus 2.7326% actual absolute movement.
An attention model entered one of the five selected block ensembles. The other
blocks used the legacy ensemble or Ridge/tree combinations selected by MAE.

October 13 had 10/25 correct directions (40%) and 3.0075 percentage-point MAE.
COHR was predicted +0.0505%, versus +4.3469% actual, an error of 4.2963 points.

Artifacts are under `work/backtest-2026-08-19_2026-10-19/results/`: the complete
CSV/JSON, daily summaries, October 13 CSV, Markdown report, daily-results chart,
and date-grouped uncertainty audit. Source snapshots and the input/source
fingerprint are retained alongside the results. Nothing was pushed or deployed.
