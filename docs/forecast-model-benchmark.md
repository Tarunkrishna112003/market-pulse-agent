# Forecast model v8

The input dataset, return target, 365-day history window, stock filters, and frozen
weekly testing records remain unchanged. Changes are local until explicitly pushed.

## Model candidates

- Ridge: regularization 1, 100, 1000; training-only constant-feature removal and robust scaling.
- Random forest and Extra Trees: two depth/leaf configurations each.
- Histogram gradient boosting: absolute-error and squared-error objectives.
- Original LSTM and original equal-weight RF/LSTM/mathematical ensemble as comparators.
- Residual MLP with feature gates, normalization, dropout, and return-only/multitask objectives.
- Gated LSTM with optional attention pooling across the five existing return lags.
- Neural alternatives compare Huber thresholds, regularization, and auxiliary tasks.

Neural models use AdamW and gradient clipping. A purged chronological tail selects
an epoch count; the model then refits on all eligible training rows for that count.
Selected new neural components receive three-seed calibration diagnostics. The
legacy LSTM remains unchanged as a comparator.

Multitask heads estimate return, direction, and 10th/90th return quantiles. Published
probabilities and intervals use historical calibration residuals for consistency
across tree and neural models; neural head probabilities are not asserted calibrated.
Feature gates and attention weights are not treated as causal explanations.

## Evaluation

Each outer fold holds out ten target trading dates. Training must precede the
first observation date in the held-out block, with all training target dates also
strictly earlier. This purges tomorrow-target intraday examples across boundaries.
Up to six outer blocks are used, subject to existing history. Fewer available
blocks are reported honestly; a minimum 60 target dates and 500 rows is required.

Within each outer training period, up to three earlier eight-target-date folds
select model settings, price/news/market feature ablations, and ensemble weights.
Weights are nonnegative and sum to one. Greedy combinations compete with the
best individual candidate and an equal-weight combination of the top candidates.
Outer labels do not select weights or hyperparameters. Each model family also
receives an outer-block comparison using its inner-selected configuration.

Metrics include MAE versus zero and historical-median baselines, direction
accuracy, empirical interval coverage, Brier score, probability bins, monthly
scores, confidence-filter retention, and a trading-date bootstrap interval for
mean daily MAE improvement. Samples sharing a target date are not treated as
independent bootstrap units. This is a date bootstrap, not a serial block bootstrap;
serial dependence across dates can still affect uncertainty estimates.

Release quality requires 2% MAE improvement over both baselines, direction accuracy
above 52%, and interval coverage at least 65%. Failed forecasts remain visible
with a low-confidence label. No predictions are hidden by confidence filters.

After evaluating the procedure, final model selection and fitting use all available
history. Calibration quantiles come from a separately purged earlier-fit tail.
Because the production model is refitted, coverage is empirical, not guaranteed.

Artifacts: `prediction-models/*-day-model.joblib` and
`prediction-models/chronological-benchmark.json` with fold results and held-out
predictions. These remain ignored locally and are uploaded by the existing CI job.

## Validation and limits

Run `python3 -m unittest discover -s scripts -p ml_prediction_test.py` and the
existing dashboard Node test suite. Synthetic tests check leakage boundaries,
learning, real candidate fitting, serialization, blending, and publication schema.
They do not establish stock prediction accuracy.

Real training is run by the existing prediction-agent workflow from its prepared
`prediction-training.json` and `prediction-sentiment.json`. No real training input
is checked into this workspace. Longer benchmarking multiplies training cost;
CPU runtime should be measured on a full real-data run before scheduling changes.
The current cohort and mixed morning/intraday samples retain their existing
selection and weighting limitations.
