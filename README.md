# NASDAQ and NYSE Movement Agent

Private dashboard and executable reporting agent. The UI loads live data automatically and saves reports. API-key entry and sample data have been removed.

## Local setup

Requires Node.js 22.13 or later. Install dependencies with `npm ci`, then copy `.env.example` to `.env`. Set `FMP_API_KEY` if available and set `LOCAL_AGENT_TOKEN` to a random private value (generate one with `openssl rand -hex 32`). Never commit `.env`.

For local headline research, install Ollama, run `ollama pull qwen3:0.6b`, and start Ollama. In separate terminals run:

```sh
npm run dev
node --env-file=.env scripts/local-agent.mjs
```

Open http://127.0.0.1:5173/. Keep both processes running for automatic scans every three hours. The background agent and Ollama must run on the same machine as the frontend server for this local workflow.

## Rules

Scan all NASDAQ and NYSE company listings, excluding non-company securities. Default filters are $20B–$100B market cap in USD, at least 5% average absolute daily movement, and 30 calendar days. Users can change cap and movement ranges and choose 1–365 days. Rank matching stocks by average absolute daily close-to-close return; display up to 25 and export every match. Trading sessions use a baseline close before the calendar window. Source failures are disclosed. Market caps are fetched at scan time; the latest daily change is an end-of-day return rather than an intraday move.

## Live UI

Open the dashboard. It displays the latest saved report and automatically starts a scan when no report exists. Run live scan refreshes it. Background uploads appear within five seconds. No API key entry or manual upload is required.

The server uses an ignored .env FMP_API_KEY when available. If the FMP screener is restricted by the subscription, the fallback reads current market caps from NASDAQ's screener and split-adjusted daily closes from Yahoo Finance. It excludes the current day's partial session before 4:15 pm Eastern. Source and market-cap as-of information appear in each report. Source failures are disclosed; the fallback was verified with live requests. These direct feeds may be delayed or temporarily unavailable.

## Unattended agent

Run:

    node --env-file=.env scripts/agent.mjs

Prints the ranking and saves outputs/report.json, even if no stocks qualify. Exits nonzero on incomplete scans. SITE_URL=http://127.0.0.1:5173 enables direct local report upload. For hosted uploads, configure AGENT_TOKEN as a hosted Site secret and in the runner. A private Site also requires its supported access mechanism for unattended HTTP requests; a bearer report token alone does not bypass Sites access control. Without this access, use screen/JSON output.

## Validation

    node --test scripts/screener.test.mjs
    npm run build

Browser WebMCP exposes read_stock_report when supported. No supported WebMCP browser context was available for runtime validation.

## Full NASDAQ and NYSE daily agent and local LLM

The local background service (`scripts/local-agent.mjs`) rediscovers all NASDAQ and NYSE company listings on each run. There is no fixed ticker list or count. It attempts daily history for every company, including those outside the report's market-cap range, then applies the original $20B–$100B and >=5% rules to the final top 25. Coverage, source failures and missing history are reported rather than assumed complete. Non-company securities such as warrants and preferred shares are excluded. Company discovery and market-cap evaluation are separate from successful price-history coverage.

After the numeric scan, the LLM reviews every company in batches of six, using fetched Yahoo Finance RSS headlines and the market data. Qwen3 0.6B runs locally through Ollama. The model selects relevant sourced headlines; output is validated against the supplied source list. The application uses source titles and links verbatim instead of allowing the model to invent price figures or causal narratives. Unknown symbols, nonexistent sources, incomplete batches and invalid JSON fail explicitly. LLM coverage is separate from successful price coverage. Full research is retained in ignored outputs/research.json; the UI shows representative batch summaries and matched-stock notes.

Automatic cadence: every three hours. The Mac must be on, connected, and logged into the configured user account. Sleep postpones due work; a minute-by-minute scheduler catches it on wake. Weekends/holidays use the last completed session. The full scan can take hours on this Mac, and the LLM stage is intentionally separate. A previous numeric report remains visible while work runs. Same-day interrupted scans resume from outputs/scan-checkpoint.json. No promise of unattended updates while this Mac is powered off.

Local agent exposes authenticated loopback-only status/start/report endpoints on port 8766. LOCAL_AGENT_TOKEN remains in ignored .env, never in the browser. The Site route proxies requests so the frontend does not need secrets. It cannot reach this Mac from a cloud-hosted deployment; this workflow is local.

Checks:

    node --test scripts/screener.test.mjs scripts/research.test.mjs


## Manual scans and CSV delivery

Run fresh scan always starts from current NASDAQ discovery and freshly fetched histories; it does not reuse a saved checkpoint. Clicking while work is running cancels/replaces that run. Startup recovery alone uses the interrupted checkpoint. Automatic scheduling continues independently.

outputs/top-25.csv contains up to 25 stocks matching the submitted filters. outputs/all-matching-stocks.csv contains every strict match, without a 25-row limit. If there are no strict matches it contains headers only. outputs/all-screened-stocks.csv includes every successful price-history result for auditing. The top-25 table never describes below-threshold stocks as matches. Numeric reports and CSVs are ready before all-universe LLM research finishes.

## Current scan cadence

The current schedule replaces the former once-daily cadence: automatically every three hours, plus a fresh scan on every Run click. The next automatic time persists in agent-status.json and is shown in the UI. A missed interval after sleep triggers one catch-up run. An automatic run replaces any earlier research still running at the three-hour boundary. Manual clicks remain available throughout. The Mac must be on and connected.

Scan complete — results below appears as soon as price scanning and report/CSV publication finish; optional LLM research has its own background status and does not hold the numeric results in a perpetual loading state. Failed histories remain disclosed.

## User-selected filters

Choose minimum/maximum market cap in USD billions, minimum average absolute daily movement, optional maximum movement, and 1–365 calendar days. Run sends all values to the authenticated local agent. Client, Worker route, and agent validate them. The full NASDAQ and NYSE scan is preserved. Only matching stocks appear in the top-25 table; every matching stock is included in the CSV. This replaces the earlier below-threshold top-25 fallback.

Last submitted filters persist in the agent status and are reused every three hours. Each report stores its own filters. Editing controls does not relabel an old report. Checkpoints include the lookback window and filter values, so interrupted data from a different window is not reused. Movement means average absolute daily close-to-close percentage change, with trading sessions drawn from the calendar-day window. The latest session can lag the current day until the market closes.

## Public dashboard on GitHub

GitHub Pages serves the separate static dashboard from `github-pages/`. The workflow `.github/workflows/scan-and-publish.yml` freshly discovers and scans every NASDAQ and NYSE company when dispatched by the code trigger, then deploys the report, searchable universe and CSV files. FMP_API_KEY is stored as a GitHub Actions repository secret. No API keys are shipped to browsers. GitHub schedules can be delayed and inactive public repository schedules may be disabled after 60 days.

Visitors can change market-cap and movement filters, and shorten the calendar window within the published history. Filters calculate results from the latest snapshot; they do not initiate a new scan. Repository writers can use the dashboard link to run the GitHub workflow manually with custom filters and a 1–365 day window. Public scheduled runs use the default 30-day, $20B–$100B, 0%–5% average movement conditions. Numeric reports are published without local Ollama research. GitHub-hosted market feeds may impose rate limits; failures and partial coverage are shown. If no valid histories return, the previous deployment is preserved.

## Price range and company news

Both dashboards show current price, 30-day trading low and 30-day trading high. The range always covers 30 calendar days ending on the scan date, independent of movement filters; histories fetch at least this window. Missing daily high/low data is shown as unavailable rather than replaced with closing prices. Yahoo prices use the latest available regular-market quote and timestamp; FMP histories use the latest closing price and date. Prices are scan snapshots, not streaming quotes. CSV exports include price, timestamp, exchange and range columns, replacing the count of large-movement sessions.

Below the results table, Investments & deals shows general Yahoo Finance news about investments, funding, acquisitions, partnerships and business deals. Every completed price scan fetches Yahoo's general RSS feed; headlines from the last seven days are selected by topic, deduplicated, sorted newest first and capped at 20. The feed is independent of table filters and company matches, including when no stocks qualify. This selects available headlines rather than guaranteeing coverage of every deal. Empty or unavailable news feeds are disclosed without failing numeric results. NASDAQ and NYSE discovery must both succeed; the scanner does not silently treat a missing exchange as complete. Older local checkpoints are invalidated to obtain the expanded universe and price history.

## GitHub scan trigger

`lib/github-scan-trigger.mjs` checks GitHub scan history and dispatches `scan-and-publish.yml` when three hours have elapsed since the last successful scan **finished**. `trigger-scan.yml` invokes `scripts/trigger-scan.mjs` every 20 minutes, at :07, :27 and :47 UTC, and can also be run manually. The first available check after the deadline starts one catch-up scan; it does not replay every missed interval. An active or queued scan prevents duplicates. Failed scans wait at least 30 minutes before retrying. The trigger uses the repository-scoped GitHub Actions token with Actions write permission; no external scheduler or additional credentials are required.

This replaces the former fixed `17 */3 * * *` scan schedule. The trigger is still invoked by GitHub scheduling, which may delay or drop checks; it improves catch-up opportunities but cannot guarantee exact three-hour timing. Scans use the public defaults (30 days, $20B–$100B cap, 0%–5% movement). Successful scan deployment completion is the interval baseline.

Validation: `node --test scripts/scan-trigger.test.mjs`.

## Stock history pages

Click a company/ticker in the first table column to open its separate daily-history page. The URL carries the applied calendar-day lookback. Each row shows Date, Low, High, Close and Daily change; weekends and holidays have no rows. The selected window determines both row count and highlighted low/high extremes. Public snapshots store daily histories as `[date, close, change, low, high]`; older three-field snapshots remain readable and display unavailable ranges as a dash. Local reports retain daily low/high fields too, and old local checkpoints are invalidated. Public history is limited to the published scan's lookback; users must run a longer scan to publish more history. Returning from the public history page preserves filter values.
