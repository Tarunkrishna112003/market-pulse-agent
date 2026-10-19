# Next-session prediction algorithm

Every prediction uses **365 calendar days of price features**, regardless of the
screener's display lookback. The target is the opening-to-closing log return of the
next unstarted trading session. Historical daily prices are fetched over a longer
800-day training archive so historical examples can each have a full year of inputs.
Full-universe scans retain one year plus a return baseline. The 30-day low/high
columns retain their fixed 30-day definition. Stocks without a complete year of
usable history do not receive a made-up forecast.

The three requested components are:

1. Random Forest: 150 trees, maximum depth 8 and minimum leaf size 20.
2. LSTM: five completed daily log returns in chronological order, 16 hidden units,
   and a separate branch for current price, volatility, market and available news
   features. CPU training uses 12 epochs, normalized targets and gradient clipping.
3. Mathematical model: regularized regression learns an intercept and feature
   coefficients from historical examples. The coefficients are not hand-set news
   multipliers. Scaling is fitted on training examples only.

Let the component predictions of log return be `r_RF`, `r_LSTM` and `r_math`.
The combined candidate uses a fixed formula:

```
training_target = log(target_session_close / target_session_open)
r_math = intercept + sum(coefficient[i] * feature[i])
r_combined = (r_RF + r_LSTM + r_math) / 3
predicted_percent_change = 100 * (exp(r_combined) - 1)
```

The future session’s open and close are historical labels only, never inference inputs. The model predicts the percentage directly; it does not need to guess the future opening price first. The scan quote remains an input, but is not the percentage denominator. Forecasts do not report a made-up dollar change or projected close anchored to that quote.

Weights are fixed before validation. The combination competes with its components
and the existing baseline models on three chronological folds. The lowest
validation MAE selects the model; the combination is not forced if it is worse.
Separate dates calibrate empirical residual ranges, and the final ten dates test
the selected model once. All stocks on the same date stay in the same partition;
training examples whose target crosses the next partition are excluded.

Historical news features use completed prior UTC-day GDELT tone buckets. Current
RSS headline sentiment is displayed as context and is not substituted into those
historical features. Missing sources are reported. Price-only candidates also
compete with candidates using news where sufficient historical coverage exists.

The current top 25 form the training cohort. Every other ticker with usable history in the full scan receives forecasts from that pooled model using separately fetched
recent daily prices. They do not have individual backtests or the same company-news
coverage. Browser filters do not run training; tickers with missing prices or insufficient history
show their availability status. Saved top-25 forecasts are evaluated against later actual closes.

The main screener table shows the selected model’s forecast percentage and target date directly. There is no separate Prediction page or validation badge. Internal held-out comparisons and a versioned forward ledger remain part of model selection; forward results use the actual target session’s close divided by its open, only after the session closes. Passing historical checks does not guarantee future accuracy.
Everything runs in GitHub Actions on CPU. No hosted prediction API is required. Batch inference applies the selected trees to all stocks. Prediction inference processes one history period at a time to bound memory use. Annual scan archives also retain volume so full-universe inference can reuse their prices. Published forecast files are split by history period so the browser downloads only the selected period.

Implementation: `scripts/forecast_models.py`, `scripts/ml-prediction.py` and
`scripts/prediction-agent.mjs`. Fitted models are saved as short-lived GitHub Actions
artifacts; Python classes remain in a stable module so artifacts can be reloaded.

## Daily market-close report

A weekday GitHub Actions schedule at 21:35 UTC starts a fresh full-universe scan
after the US close in both daylight and standard time. The NYSE calendar skips
holidays; the ordinary three-hour scans also create the report when eligible.
GitHub may delay scheduled runs, so this is not an exact-time delivery guarantee.

After a completed session, the report filters to $20B–$200B inclusive and 0–5%
average absolute daily movement over the past 365 calendar days. It ranks by that
movement, descending, selects up to 25 stocks and attaches their one-year-model
predictions for the next session's open-to-close percentage. This is the existing
screener movement measure, not statistical variance.

The first published report for each closing date is preserved. The JSON, Markdown and CSV reports remain published as data exports. The
dashboard now links directly to the simple Testing results comparison page. Dated copies are saved
as GitHub Actions artifacts for 90 days. Intraday publications preserve the previous
closing report. A report records source failures and leaves unavailable forecasts
blank rather than substituting zero.

## One-week testing results

The Testing results button opens a fixed-cohort test for October 19–23, 2026.
The 25 stocks are copied once from the latest published daily report. A morning
update reads the already-public one-year forecast feed and saves the first eligible
prediction for that same trading day before 6:00 AM America/Los_Angeles. It records
when that value was observed publicly, and never replaces it with a later forecast.
Missing the cutoff is recorded as a miss, even if a later prediction exists.

Morning publishing checks run at :05 and :40 during 12:00–14:59 UTC, covering both
Pacific offsets. A fresh full scan is also scheduled at 11:05 UTC, ahead of the
cutoff. Closing comparisons update at 21:55 UTC and after ordinary publications,
using actual same-day open and close prices. GitHub schedules can be delayed;
missed cutoffs are not concealed or backfilled. The page compares saved percentage,
actual percentage, direction and absolute percentage-point error.
