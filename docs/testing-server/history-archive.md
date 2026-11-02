# GitHub-hosted historical stock archive

Branch: `testing-server`. The live website and production training remain unchanged.

The initial job runs on GitHub-hosted Ubuntu runners. Full history collection is explicitly blocked on laptops and self-hosted runners. Source files and fixture tests can be developed locally; actual market-history downloads take place on GitHub.

## Storage and scope

- GitHub prerelease `testing-stock-history-v1` stores the frozen initial universe, compressed CSV chunks, immutable coverage manifests, and eight small, rebuildable checkpoints.
- Discovery reads the complete NASDAQ and NYSE listings, without market-cap, volatility, or top-25 restrictions. Provider metadata classifies supported exchange equities; excluded/non-equity instruments and failed symbols remain visible in coverage metadata.
- The daily request starts at 1900-01-01, allowing pre-1970 records. This means **all history available from the provider**, not guaranteed IPO-to-present completeness. The initial universe contains current listings and does not reconstruct delisted companies or historical index membership.
- CSV columns: `symbol,interval,timestamp,session_date,open,high,low,close,volume,adjusted_close,corporate_actions,observed_at,source`.
- `interval=1d` denotes daily OHLCV. Timestamps are Unix seconds; session dates use New York time. OHLCV is provider-reported, and adjusted close and corporate actions are preserved separately. Future provider adjustments may revise historic prices.
- A manifest records SHA-256, schema, exact row count, columns, commit, coverage dates, provider first-trade timestamp, rejected rows, warnings, and each ticker's outcome. A successful request is not a guarantee of complete market history.
- The CSV is gzip-compressed, not committed into Git history. A chunk is kept below 500 MiB; normal chunks contain at most 50 tickers.

## Resume and append behavior

Eight deterministic symbol partitions run with at most four GitHub runners concurrently. A completed CSV is uploaded before its immutable manifest. Only then is the shard's small checkpoint advanced. Historical CSVs and manifests are never clobbered. Only the rebuildable checkpoint metadata is replaced.

A rerun skips successfully backfilled or unsupported listings and retries failures. A lost checkpoint can cause an overlapping redownload, not deletion of history. Recover by replaying immutable manifests, then rebuild the checkpoint before the next collection. Do not delete release assets as part of a normal scan.

Every append carries its observation time. Consumers merge by `(symbol, interval, session_date)` for daily bars, or `(symbol, interval, timestamp)` for intraday bars, preferring the latest observation. They retain all immutable originals to audit revisions. A newly reported stock split triggers a full daily-history revision for that ticker.

## Running the jobs

Pushing archive code to `testing-server` triggers the initial backfill. In Actions, **Testing server stock history archive** can also be run manually against `testing-server`:

- `mode=backfill`: complete or resume initial daily histories.
- `mode=update`: append recent completed five-minute bars, plus completed daily bars after the scheduled close and a 15-minute delay. Updated CSVs/manifests are stored in `testing-stock-updates-YYYY-MM-DD` releases.

Updates request an overlap around the last saved bar, so a delayed run catches up rather than discarding everything older than its most recent 30 minutes. Initial intraday collection requests seven days. The provider has limited intraday retention; gaps older than the configured 58-day safe window are explicitly reported. Failed requests never advance a ticker's data watermark.

Update jobs skip weekends and times outside 09:30–16:45 Eastern. No premarket/after-hours feature training is enabled. Daily bars and the final five-minute bar remain excluded until complete. After early closes, the same close-time checks govern completed daily labels.

## Scheduling and training status

**This first phase archives data; it does not yet enable autonomous model training or a 30-minute timer.** GitHub's cron workflows execute from the default branch, so a workflow committed only to `testing-server` is not a functioning scheduler. Enabling a default-branch dispatcher or another GitHub-approved trigger is a separate step; do not claim scheduling works before it is installed and verified.

When the archive is ready, a training job can download CSV chunks to a temporary GitHub runner, train from a persisted checkpoint, and save a new version back to GitHub. That temporary runner disk is not the user's laptop. The daily open-to-close model can update with newly completed daily outcomes; five-minute collection does not produce a completed daily label every 30 minutes. Model continuation, temporal validation, promotion rules, and saving model checkpoints still need implementation before autonomous training is enabled.

Free chart endpoints have no guaranteed service level. A free full-universe collection may take longer than 30 minutes; show actual collection lag rather than treating it as fresh. Failed tickers, missing years, unavailable symbols, and retention gaps must be reported, never filled with invented bars.

## GitHub limits

GitHub Releases permit up to 1000 assets per release, with each asset below 2 GiB. Compressed chunks keep source-code clones small. Normal Actions artifacts expire and are not the permanent archive. The update layout uses one CSV plus one manifest per shard per run: eight shards, 14 regular-session runs, and eight checkpoints remain comfortably below the daily release asset count. Excess manual runs still count toward the limit. The collectors do not purchase data or provision paid runners.

References:
- https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html
