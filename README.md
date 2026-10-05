# NASDAQ Movement Agent

Private dashboard and executable reporting agent. The UI initially shows fictional examples, clearly labeled. No live results or active schedules are claimed until market-data access is configured.

## Rules

NASDAQ-listed active stocks, excluding ETFs/funds. Current provider market cap between $20 billion and $100 billion inclusive, in USD. Last 30 calendar dates in America/New_York, inclusive. Trading sessions only; baseline closing price before the window. Split-adjusted close-to-close price returns (FMP full EOD endpoint), no dividend total-return adjustment. Rank by arithmetic mean of absolute daily returns >= 5%, descending; at most 25. Missing baseline or provider failures are disclosed; any failure marks the report partial. Latest daily change is the last available EOD return, not an intraday move. Market caps are retrieved at scan time, not historical per-day caps.

## Live UI

Open Agent setup, enter an FMP key with access to company-screener and historical-price-eod/full, then run a scan. The key lives in React memory for that page session. It is never persisted. The scan runs sequentially while the page is open. Reports persist in D1. Endpoint access, rate limits and availability depend on the FMP subscription. Live-provider integration has not been verified without a key.

## Unattended agent

Configure .env with FMP_API_KEY and run:

    node --env-file=.env scripts/agent.mjs

Prints the ranking and saves report.json, even if no stocks qualify. Exits nonzero on incomplete scans. Optional SITE_URL and AGENT_TOKEN enable report upload: configure the same AGENT_TOKEN as a hosted Site secret. A private Site also requires its supported access mechanism for unattended HTTP requests; a bearer report token alone does not bypass Sites access control. Without this access, use screen/JSON output.

For weekdays at 6:30 pm America/New_York, on a runner whose timezone is Eastern:

    30 18 * * 1-5 cd /absolute/path/market-pulse-agent && /absolute/path/node --env-file=.env scripts/agent.mjs >> agent.log 2>&1

Install only after setting the key and verifying a successful run. On this Mac in Pacific time the equivalent is 15:30 weekdays. Cron requires the computer to be awake. Exchange holidays may show the previous session. No schedule has been installed. Email was not selected; output is on screen and in JSON.

## Validation

    node --test scripts/screener.test.mjs
    npm run build

Browser WebMCP exposes read_stock_report when supported. No supported WebMCP browser context was available for runtime validation.
