# October 29 direct-return model switch

User-selected production model: `daily-open-to-close-v10-direction-aware`. Configuration: `data/prediction-model.json`.

The model directly learns signed open-to-close percentage returns with pseudo-Huber loss plus a directional logistic penalty. It uses the same direction-aware configuration evaluated in the October 27 experiment: one-year training window, 150 boosting rounds, 15 leaves, depth 5, learning rate 0.035 and seed 42. It has no probability-calibration layer, pooled-median percentage calculation, forced sign balance or legacy-model fallback. Its historical joint improvement gate did not pass; the user explicitly selected it for forward use.

The shared training cohort includes the current top 25 and a sector-balanced selection of up to 100 liquid large/mid-cap stocks. Every scanned ticker receives its own price/volume and market/sector-relative input vector. Other stocks reuse archived complete OHLCV with short refreshes, rather than repeatedly downloading full histories. The selected shared model uses a 365-day label window; older bars provide feature warm-up. Separate per-stock fitting remains supported but is not the active selection.

Before market close the selected model can forecast the current session; after close it targets the next trading session. All inputs come from completed sessions before the target date. Today's current-session quotes and opening price are not inputs. Predictions generated after the open are explicitly labelled. They are full-session open-to-close estimates, not forecasts of the remaining intraday move.

Today's new forecasts are recorded separately in `lateForecasts`; October 29's original morning predictions are retained. Late forecasts do not enter the strict morning-test summary or its validation denominator. October 30's normal before-cutoff capture uses the new model version. The prediction ledger separates model versions and retains the first saved forecast per version, stock and target session.

The model has not been trained for close-to-close returns; that estimate is unavailable instead of being silently supplied by the old model. Invalid histories produce no signal. Model fitting and source errors remain visible in diagnostics.

Validation before publication: 37 Node checks and 23 Python checks passed in an isolated copy containing only the deployment changes. Tests cover future-price poisoning, joint-loss derivatives, feature sensitivity, stock-specific fitting, corporate-action flags, session targeting, serialization, frozen-morning preservation and separate after-open scoring. A fresh-price 100-stock deployment check generated 24 usable cohort predictions for October 29 (14 positive, 10 negative); one cohort stock lacked clean history. These counts describe the deployment check, not an accuracy result or a requirement imposed on the model.
