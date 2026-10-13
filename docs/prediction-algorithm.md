# Next-session prediction algorithm

For each 10-, 20- and 30-calendar-day feature window, predict the log return from
the scan quote to the close of the next unstarted trading session. Training uses
longer price archives; the selected window controls the information used in each
historical example. Holidays, pre-open forecasts and completed intraday bars are
handled by the existing trading calendar.

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
r_math = intercept + sum(coefficient[i] * feature[i])
r_combined = (r_RF + r_LSTM + r_math) / 3
predicted_percent_change = 100 * (exp(r_combined) - 1)
predicted_close = scan_price * exp(r_combined)
predicted_dollar_change = predicted_close - scan_price
```

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

The current top 25 form the training cohort. Other tickers in the scan's configured
market-cap band receive forecasts from that pooled model using separately fetched
recent daily prices. They do not have individual backtests or the same company-news
coverage. Browser filters do not run training; tickers outside that published band
show `Not covered`. Saved top-25 forecasts are evaluated against later actual closes.

Models failing the existing held-out error, direction or interval-coverage gates
show `No reliable signal` by default. Raw forecasts remain reviewable on the
Prediction page. Passing historical checks does not guarantee future accuracy.
Everything runs in GitHub Actions on CPU. No hosted prediction API is required.

Implementation: `scripts/forecast_models.py`, `scripts/ml-prediction.py` and
`scripts/prediction-agent.mjs`. Fitted models are saved as short-lived GitHub Actions
artifacts; Python classes remain in a stable module so artifacts can be reloaded.
