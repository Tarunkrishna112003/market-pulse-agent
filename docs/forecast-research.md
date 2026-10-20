# End-to-end prediction research

All changes remain local. The raw OHLCV dataset, saved 25-stock cohort, return
target, historical cutoff, and original weekly prediction records are preserved.

## Stages implemented and tested

1. **Inputs:** historical features exclude the anchor day and later prices.
2. **Features:** add recent open-to-close lags, 5/20/60-session statistics,
   prior overnight gaps, volume/range indicators, RSI, recent market movement,
   historical beta, target weekday and stock identity. The resulting vector has
   84 features derived from the same existing data.
3. **Training:** balance repeated observations of each stock/target, prioritize
   morning examples, and apply a fixed 60-calendar-day recency half-life.
4. **Targets:** compare raw-return regression and trailing-volatility normalization.
5. **Direction:** train logistic and boosted classifiers directly on up/down
   outcomes; calibrate their probabilities using earlier dates.
6. **Magnitude:** convert probability and earlier signed-magnitude distributions
   into a conditional median return. This avoids assuming that an uncertain
   directional forecast should have the full expected absolute daily movement.
7. **Numerics:** retry logistic fitting with a larger iteration budget when the
   original solver limit is reached; do not silently accept convergence warnings.
8. **Selection:** compare individual models and blends. A joint gate requires
   at least 0.5% lower MAE and 2 percentage points higher direction accuracy on
   earlier validation dates; otherwise retain v7.
9. **Validation:** freeze the procedure choice from Aug 19–Sep 30 before the new
   Oct 1–19 confirmation predictions. The original results for the period were
   already inspected, so this is exploratory research, not an untouched test.
10. **Forward check:** freeze a separate local comparison for the next session
    before its morning cutoff. Preserve the original forecasts when evaluating.

The original dataset's mix of daily and intraday examples remains present. Changes
to training weights do not remove raw observations. No current news is substituted
for unavailable historical news snapshots.

## Completed results

43 trading sessions × 25 stocks = 1,075 comparisons for every main procedure.

| Procedure | Direction accuracy | Mean absolute error (percentage points) |
|---|---:|---:|
| Committed v7 replay | 50.51% | 2.7327 |
| Prior local v8 replay | 47.53% | 2.7429 |
| New direction-boosted candidate | 52.37% | 2.7197 |
| Always predict zero | — | 2.7326 |

The candidate improves observed direction by 1.86 percentage points and observed
MAE by about 0.47% relative to v7 over the full period. Its improvement is small
and the date-block uncertainty intervals include no improvement. It did not pass
the predeclared joint development gate: its development direction was 53.07%,
versus v7's 53.33%, even though its development MAE was lower. The global automatic
choice therefore remains v7. The candidate is retained as a promising research
model, not silently promoted by choosing the best October result afterward.

The candidate's nominal 80% interval covered 72% of confirmation outcomes, so its
uncertainty ranges also need further validation. The forward file's `candidate80Range`
refers to nominal quantiles, not a proven 80% coverage guarantee.

Controlled feature/weighting ablations are saved separately. Some transformations
help one metric or model and worsen another. Additional features and complexity
are not assumed to improve every stage.

## Prospective local comparison

Target: **2026-10-20**. Forecasts were frozen at **2026-10-20 06:11:05 UTC**,
before the **13:00 UTC / 6 AM Pacific** cutoff. Inputs and training outcomes stop
at October 19. The file contains all 25 stocks, with candidate, v7 and v8 forecasts;
it includes no target-day actuals. It does not modify the website's weekly results.

Once the target session closes:

```sh
node scripts/evaluate-forward-comparison.mjs
```

The evaluator refuses to score before market close and writes a separate actual
comparison file, preserving the frozen forecasts.

## Code and artifacts

- `scripts/forecast_features.py`: past-only feature derivation.
- `scripts/forecast_research.py`: weighted models, direction probabilities and joint gate.
- `scripts/improve-forecast-models.py`: historical research runner.
- `scripts/forecast_ablation.py`: controlled feature/weighting comparisons.
- `scripts/freeze-forward-comparison.py`: exclusive creation of local forward forecasts.
- `scripts/evaluate-forward-comparison.mjs`: after-close evaluation.
- `work/forecast-research-2026-08-19_2026-10-19/converged/`: corrected research report,
  CSV/JSON comparisons, frozen daily predictions, selection diagnostics and audit.
- `work/forecast-research-2026-08-19_2026-10-19/ablations/`: controlled comparisons.
- `work/forecast-research-2026-08-19_2026-10-19/forward/2026-10-20.json`: frozen
  prospective forecasts; fitted models are stored alongside it.

The initial pilot is retained for provenance. It exposed a logistic iteration-limit
warning; the reported results above use the corrected, converged run.

Research can be resumed with unchanged inputs:

```sh
MARKET_PULSE_RESEARCH_OUTPUT="$PWD/work/forecast-research-2026-08-19_2026-10-19/converged" \
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 python3 scripts/improve-forecast-models.py
```

Validation completed: 30 Python tests and 46 Node tests passed. These check numerical
fitting, leakage boundaries, model serialization, weighting, probability/magnitude
logic, calibration, matched comparisons and the existing dashboard behavior. They
do not establish future market performance.


## October 20 model switch

The active pipeline now fits the `direction_boosted` recipe through
`scripts/forecast_runtime.py` under model version
`annual-open-to-close-v9-direction-boosted`. It retains the 365-calendar-day
training outcome window, 90-day intraday window, past-only enhanced features,
grouped recency weights, earlier-fit probability calibration and signed
volatility-scaled magnitude distributions. The latest ten completed morning
sessions provide chronological diagnostics; this model remains experimental.
The old candidate-selection machinery remains available for research and is
not called by the active prediction pipeline.

The October 20 testing results use the exact 25 forecasts frozen at
2026-10-20T06:11:05.714567Z (October 19, 11:11 PM Pacific), not a recalculation.
The original file is committed under `data/frozen-forecasts/2026-10-20.json`
and verified with its original SHA256. This is an explicitly authorized
one-time switch from previously public v7 predictions to locally frozen
forecasts; provenance records that they were not public at generation time.
Original October 20 v7 predictions are retained in `previousPredictions`.
October 19 entries are preserved without modification by the migration.
Normal future daily capture remains first-write immutable.
