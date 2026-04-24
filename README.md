# sniper-streamer — Usage Tutorial

---

## Table of contents

1. [What this tool is (and isn't)](#1-what-this-tool-is-and-isnt)
2. [Key concepts, in plain language](#2-key-concepts-in-plain-language)
3. [Running it](#3-running-it)
4. [The three-panel layout](#4-the-three-panel-layout)
5. [The main screener table — column by column](#5-the-main-screener-table--column-by-column)
6. [The "Liq Clusters (1h)" panel (bottom right)](#6-the-liq-clusters-1h-panel-bottom-right)
7. [The "Alerts" panel (bottom left)](#7-the-alerts-panel-bottom-left)
8. [Color legend — quick reference](#8-color-legend--quick-reference)
9. [How to use this for margin sniping](#9-how-to-use-this-for-margin-sniping)
10. [Tuning the thresholds](#10-tuning-the-thresholds)
11. [Honest limitations](#11-honest-limitations)

---

## 1. What this tool is (and isn't)

`sniper-streamer` is a **read-only context dashboard** for Hyperliquid
USDC-margined perpetual futures. It subscribes to public WebSocket streams
and polls the public info endpoint to show you, in real time:

- Where perp prices are relative to Hyperliquid's oracle/reference price
- Who is crowded and how hard (funding, open interest, taker flow)
- WebSocket feed health via per-symbol drift

It does **not** place orders, it does **not** give trade signals you should
blindly follow, and it does **not** replace real risk management. It's a
screener that helps you *see* structural pressure building up so you can
form your own thesis.

Note: Hyperliquid's official public market subscriptions do not expose an
all-market liquidation stream equivalent to Binance `!forceOrder@arr`. The
liquidation columns, liquidation-cluster panel, and liquidation-dependent
alerts are therefore disabled by default unless you add a separate liquidation
data source.

---

## 2. Key concepts, in plain language

**Mark price** — the "fair" price the exchange uses to decide who gets
liquidated. Different from the last trade price, and this difference is
what makes a "wick-based" liquidation possible vs not.

**Funding rate** — a small payment that flows between longs and shorts.
Hyperliquid funding settles hourly. When more people are long than short,
longs pay shorts (positive funding). Extreme funding means crowded
positioning.

**Open interest (OI)** — the total number of contracts currently open.
Rising OI with rising price = new longs. Rising OI with falling price =
new shorts. OI collapsing = positions are being closed or liquidated.

**Basis** — the gap between the perp mark and Hyperliquid's oracle/reference
price, expressed as a percentage. Positive basis = perp trades above the
oracle; negative basis = perp trades below it.

**CVD (Cumulative Volume Delta)** — the running sum of aggressive buy
volume minus aggressive sell volume. An "aggressive buy" is a trade
where the taker lifted the offer; an "aggressive sell" is a trade where
the taker hit the bid. CVD tells you who is in a hurry — the people
crossing the spread.

**Liquidation** — when a leveraged position gets forcibly closed by the
exchange. A long liquidation is a forced SELL order; a short liquidation
is a forced BUY order. The current official Hyperliquid public market feed
does not provide the all-market liquidation stream this dashboard used on
Binance, so liquidation views show `off`.

---

## 3. Running it

```bash
cd sniper-streamer
./sniper-streamer.sh
```

or, equivalently:

```bash
.venv/bin/python main.py
```

The dashboard takes over the full terminal (`screen=True` in
`dashboard.py`). Press `Ctrl+C` to quit. When it starts, OI delta columns
show `-` until enough Hyperliquid info snapshots have been collected at
runtime.

The watchlist lives in `config.py`:

```python
WATCHLIST = ["btc-usdc", "eth-usdc", "icp-usdc", "sol-usdc", "doge-usdc", "bnb-usdc"]
```

Edit and restart to track different symbols.

---

## 4. The three-panel layout

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│           MAIN SCREENER TABLE  (one row per symbol)    │
│                                                        │
├────────────────────────┬───────────────────────────────┤
│                        │                               │
│        ALERTS          │       LIQ CLUSTERS (1h)       │
│     (bottom left)      │       (bottom right)          │
│                        │                               │
└────────────────────────┴───────────────────────────────┘
```

The top panel takes ~3/4 of the screen height, the two bottom panels
share the rest. The whole thing refreshes twice per second
(`DASHBOARD_REFRESH_HZ = 2`).

---

## 5. The main screener table — column by column

One row per symbol in your watchlist. Columns left to right:

### Symbol

Just the ticker in bold (e.g. `BTC-USDC`). No color coding.

### Mark $

The current mark price, shown with 4 decimals. Mark price — not last
trade price — is what the exchange uses to compute liquidations. If the
mark is 0 (no data yet), this cell shows a dim `-`.

### Funding%

The current Hyperliquid funding rate from `activeAssetCtx`, shown as a
percentage (e.g. `+0.0123%`). Hyperliquid funding settles hourly.

**Colors (from `_fmt_funding` in `dashboard.py`):**

| Color | Meaning | Threshold |
|---|---|---|
| **bold red** | Extreme positive funding — longs are paying a lot, crowded long | `> +0.10%` |
| **bold green** | Extreme negative funding — shorts are paying, crowded short | `< −0.10%` |
| white | Within normal range | between |

The `±0.10%` thresholds come from `config.ALERT_FUNDING_PCT`. When a
cell turns bold red or bold green, the FUNDING alert also fires.

### Basis%

The perp-vs-oracle gap, computed as `(mark − oraclePx) / oraclePx × 100`,
shown with 3 decimals. Positive = perp trades above the oracle, negative =
perp below the oracle. Uses standard `_signed` coloring:

| Color | Meaning |
|---|---|
| green | Positive basis (perp premium) |
| red | Negative basis (perp discount — often forced-selling territory) |
| dim | Exactly zero / no data |

For sniping context, a *deeply* negative basis (worse than `−0.3%`) can
still flag stressed perp pricing, but the CAPITULATION alert remains
disabled until liquidation data is available.

### OI Δ15m% and OI Δ1h%

Percent change in open interest over the last 15 minutes and last hour
respectively. OI samples are polled every 60 seconds into
`OIHistory._samples` and the delta is computed by
`OIHistory.delta_pct()` in `state.py`. Same `_signed` coloring as basis
(green positive, red negative).

**Reading these:**
- **OI rising + price rising** → new longs opening (leverage building on the long side)
- **OI rising + price falling** → new shorts opening (leverage building on the short side)
- **OI falling** → positions closing — either voluntarily or by liquidation

The 1h alert fires at `±3.0%` (`ALERT_OI_DELTA_1H_PCT`).

### CVD 5m $

Signed taker notional over the last 5 minutes, in dollars. Computed by
`TradeWindow.cvd()` as buy-taker volume minus sell-taker volume.
Formatted as `+X.XXM` when ≥ $1M, otherwise `+X.Xk`.

**Important — the color convention here is INVERTED from what you'd
expect** (see `_fmt_cvd` in `dashboard.py`):

| Color | Value | Meaning for sniping |
|---|---|---|
| **red** | positive (buyers are aggressive) | Crowded-long warning — fuel for a squeeze |
| **green** | negative (sellers are aggressive) | Potential exhaustion / reversal setup |
| dim | zero | no flow |

This is deliberate. Conventional charting software colors CVD-up green,
but from a sniping perspective, aggressive buying is the *warning*, not
the all-clear. You're watching for moments where aggressive buyers
exhaust themselves into overhead liquidation clusters — so red here
means "pay attention."

### Taker% 5m

The fraction of 5-minute taker volume that was aggressive *buying*,
expressed 0–100. Computed by `TradeWindow.taker_pct()`. 50% means
balanced — equal amounts of buyers and sellers crossing the spread.

**Colors (from `_fmt_taker_pct`):**

| Color | Range | Meaning |
|---|---|---|
| **bold red** | ≥ 60% | Crowded buying — taker flow dominated by aggressive longs |
| red | ≥ 55% but < 60% | Leaning buy-heavy |
| dim | 45%–55% | Balanced |
| green | ≤ 45% but > 30% | Leaning sell-heavy |
| **bold green** | ≤ 30% | Crowded selling — capitulation territory |
| dim `-` | None | No volume yet in the window |

The 60% / 30% thresholds come from `ALERT_TAKER_HIGH_PCT` /
`ALERT_TAKER_LOW_PCT`.

Same inverted logic as CVD: the "danger" color from a sniping standpoint
is red (crowded buying, fragile), because that's the setup that
cascades when it unwinds.

### Top Cluster

Shows `off` by default because Hyperliquid's official public market feed
does not expose an all-market liquidation stream. If you wire in a separate
liquidation source and set `LIQUIDATION_FEED_ENABLED = True`, this column
shows the **largest** liquidation cluster in the last hour as a distance
from the current mark price, plus an arrow and a side letter. Format:

```
0.42% ↑L
```

**Reading it:**
- `0.42%` is how far the cluster price sits from the current mark price
  (absolute value — the arrow tells you the direction)
- `↑` means the cluster is **above** the current mark
- `↓` means the cluster is **below** the current mark
- `L` means **longs got liquidated** at that level (dominant side was
  SELL-side forced orders)
- `S` means **shorts got liquidated** at that level (dominant side was
  BUY-side forced orders)

**Colors — this column has special position-aware logic** (from
`_fmt_top_cluster` in `dashboard.py`):

| Display | Color | Interpretation |
|---|---|---|
| `↑L` (longs wiped overhead) | **red** | Likely resistance on retest — shorts defended, longs got flushed there before |
| `↓S` (shorts wiped below) | **green** | Likely support on retest — longs defended, shorts got covered there before |
| `↑S` or `↓L` ("cross-grain") | **yellow** | Unusual configuration — longs wiped below the mark, or shorts wiped above. Worth extra attention because it often means a rejection already happened. |
| `-` | dim | No cluster yet (needs ≥ 2 liquidation events at a similar price in the last hour) |

This is the most strategically important column for sniping setups.
The cross-grain (yellow) case is particularly interesting: if `↑S`
appears, shorts just got squeezed at a price *above* the current mark,
meaning price already rejected and fell back — that overhead level is
now a magnet for the next run.

### Liqs 5m L/S

Shows `off` by default. With a liquidation feed enabled, this is the count
of liquidation **events** in the last 5 minutes, split by which side got
wiped:

```
7/2
```

means 7 long liquidations (forced SELLs) and 2 short liquidations
(forced BUYs) in the last 5 minutes.

| Color | Part | Meaning |
|---|---|---|
| red | the `L` count (first number) | Longs getting forcibly closed |
| dim | the `/` separator | — |
| green | the `S` count (second number) | Shorts getting forcibly closed |

The interpretation depends on the liquidation source you add; each venue or
indexer has different throttling and aggregation behavior.

### Liq $ 5m

Shows `off` by default. With a liquidation feed enabled, this is the total
notional USD of all liquidations in the last 5 minutes.

| Color | Threshold |
|---|---|
| **bold red** | ≥ $2,000,000 (`ALERT_LIQ_VOL_5M_USD`) — major liquidation event |
| white | below threshold |
| dim `-` | zero |

When this turns bold red, the LIQ_VOL alert fires.

### Drift ms

Milliseconds since the last WebSocket event for this symbol — a health
check, not a market signal. If drift starts climbing, your connection
or the feed is having issues.

| Color | Drift value |
|---|---|
| dim | ≤ 2000 ms (healthy) |
| yellow | > 2000 ms (stale — worth watching) |
| red | > 5000 ms (something is wrong) |

---

## 6. The "Liq Clusters (1h)" panel (bottom right)

This panel shows a disabled message by default because the official public
Hyperliquid market feed does not provide all-market liquidation executions.
If you wire in a separate liquidation source and set
`LIQUIDATION_FEED_ENABLED = True`, it lists up to the **top 2 liquidation
clusters per symbol** over the last hour (`window_ms=3_600_000`,
`min_count=2`). A "cluster" is a set of liquidation events that happened at
similar price levels, bucketed into price bins of 0.1% of the current mark
(`LIQ_CLUSTER_BUCKET_PCT = 0.1` in `config.py`).

### Line anatomy

Each line looks like this:

```
BTC-USDC ↑L @ 95,000.5000  0.25% away  ×5 $1,234,567
│       │ │  │            │            │  │
│       │ │  │            │            │  └─ Total USD notional of liquidations in this cluster
│       │ │  │            │            └──── Number of liquidation *events* in this cluster
│       │ │  │            └─────────────────  Distance from current mark price to the cluster
│       │ │  └──────────────────────────────  Price level of the cluster
│       │ └─────────────────────────────────  L = longs were liquidated / S = shorts were liquidated
│       └───────────────────────────────────  ↑ = cluster above mark / ↓ = cluster below mark
└───────────────────────────────────────────  Symbol
```

Breaking each piece down:

**Symbol** — bold white, just the ticker.

**Arrow (`↑` or `↓`)** — direction from the current mark price:
- `↑` the cluster price is **higher** than the current mark
- `↓` the cluster price is **lower** than the current mark

**Side letter (`L` or `S`)** — who got wiped at this level:
- `L` = **LONG** cluster — longs were forcibly sold out. These show up as
  side=`SELL` forced orders because closing a long position means selling.
- `S` = **SHORT** cluster — shorts were forcibly covered. These show up
  as side=`BUY` forced orders.

**`@ 95,000.5000`** — the cluster price (the center of the price bucket
where the liquidations occurred).

**`0.25% away`** — distance from the current mark price to the cluster
price, as a percentage. Doesn't say direction (the arrow already did
that) — just magnitude.

**`×5`** — the count of **liquidation events** that happened inside this
price bucket. "Events" here means individual liquidation messages that came
through the configured liquidation source.

**`$1,234,567`** — the total USD notional of all those liquidations
combined (each event's `qty × price` summed within the bucket).

### Colors in this panel

The color logic here is **simpler than the Top Cluster column** in the
screener — it's purely based on which side got wiped:

| Display | Color | Meaning |
|---|---|---|
| `↑L` or `↓L` | **red** | Long cluster — wherever on the chart, longs got hurt there |
| `↑S` or `↓S` | **green** | Short cluster — shorts got hurt there |

So in this panel, red and green are not "good/bad" — they're just a
quick visual coding of which cohort was forced out. The **direction**
arrow is what tells you whether the cluster is a potential resistance
(above) or support (below).

**If the panel shows "No clusters…"**, it means no symbol has had ≥ 2
liquidation events in the same 0.1%-wide price bucket within the past
hour. Quiet market.

---

## 7. The "Alerts" panel (bottom left)

Shows up to the **10 most recent alerts**, newest on top. Each alert is
deduplicated within a 5-minute window per `(symbol, kind)` pair — so a
condition that stays true doesn't spam the log every refresh.

### Line anatomy

```
[14:23:07] BTC-USDC LONG_SQUEEZE fund +0.0612%  OI +4.2%  tkr 68%  ↓L cluster -0.25% away
│          │        │           │
│          │        │           └─ The message body (details vary by alert kind)
│          │        └─── Alert KIND (colored by type — see below)
│          └─────────── Symbol in bold white
└──────────────────── Timestamp in dim (UTC, HH:MM:SS)
```

### Alert kinds and what they mean

There are **seven** alert kinds in total, split between simple
threshold alerts and composite setup alerts. All firing logic lives in
`alerts.py`.

#### Simple threshold alerts

These fire when a single metric crosses a line.

##### FUNDING (yellow)

```
FUNDING rate +0.1234% (±0.1% threshold)
```

- Triggers when the absolute value of funding (`st.funding * 100`)
  exceeds `ALERT_FUNDING_PCT` (default 0.10%).
- The message shows the actual rate and the threshold it breached.
- Standalone, this just says "positioning is one-sided." Not a trade
  signal by itself — wait for it to pair with OI movement or a
  cluster.

##### LIQ_VOL (bold red)

```
LIQ_VOL 5m vol $2,345,678 (threshold $2,000,000)
```

- Disabled by default on Hyperliquid because `LIQUIDATION_FEED_ENABLED = False`.
- Triggers when total liquidation notional in the last 5 minutes
  exceeds `ALERT_LIQ_VOL_5M_USD` (default $2M).
- The message shows actual 5m liquidation USD vs the threshold.
- A big-dollar cascade just happened — the question is whether this is
  the START of a bigger move or the END.

##### OI_1H (magenta)

```
OI_1H 1h OI Δ +4.15% (±3% threshold)
```

- Triggers when 1-hour OI change exceeds `ALERT_OI_DELTA_1H_PCT`
  (default ±3%).
- Positive = leverage is **building**. Negative = leverage is **being
  unwound** (either closing voluntarily or getting liquidated).

##### CLUSTER (cyan)

```
CLUSTER stop cluster @ 95,000.5000  x5 events  $1,234,567
```

- Disabled by default on Hyperliquid because `LIQUIDATION_FEED_ENABLED = False`.
- Triggers when `st.liq_clusters()` — with its default 5-minute
  window and `min_count=3` — returns at least one cluster. The alert
  reports the top one by notional.
- **`@ 95,000.5000`** — the price level where the cluster formed.
- **`x5 events`** — the number of liquidation events detected in that
  price bucket over the last 5 minutes.
- **`$1,234,567`** — total USD notional liquidated at that level.
- Note: unlike the 1-hour Liq Clusters panel on the right, this alert
  uses the tighter 5-minute window and a higher minimum event count,
  so it's specifically flagging *just-happened* clusters.

#### Composite setup alerts

These fire only when *several* conditions line up at once — which is
where the actionable edge lives.

##### LONG_SQUEEZE (bold red) {#long-squeeze-setup}

```
LONG_SQUEEZE fund +0.0612%  OI +4.2%  tkr 68%  ↓L cluster -0.25% away
```

Disabled by default on Hyperliquid because it depends on liquidation
clusters.

Fires when **all four** of these are true:
1. Funding% ≥ 0.05% (`ALERT_FUNDING_SQUEEZE_PCT`) — longs are paying
2. 1h OI Δ ≥ +3% — leverage is building
3. 5m taker% ≥ 60% — buying tape is crowded
4. There is at least one long-dominated liquidation cluster *below*
   the current mark, within the last hour

Reads as: "the setup is loaded — longs are paying up, new longs are
piling in, buyers are aggressive, and there's a stack of long stops
sitting below price waiting to get run." A flush that reaches the
cluster at `−0.25%` below mark is a candidate sniping target.

The `↓L cluster -X.XX% away` at the end tells you how far below the
mark the nearest long cluster sits.

##### CAPITULATION (bold green) {#capitulation-setup}

```
CAPITULATION liq $823,456  CVD -1.45M  tkr 22%  basis -0.412%
```

Disabled by default on Hyperliquid because it depends on liquidation
notional.

Fires when **all four** are true:
1. 5m liquidation notional ≥ $500K (`ALERT_LIQ_CAPITULATION_USD`)
2. CVD 5m ≤ −$500K (`ALERT_CVD_SHARP_NEG_USD`) — aggressive selling
3. 5m taker% ≤ 30% — crowded selling tape
4. Basis ≤ −0.3% (`ALERT_BASIS_CAPITULATION`) — perp trading at a
   meaningful discount to spot

Reads as: "forced sellers are hammering the perp book harder than spot
can absorb." These conditions historically mark short-term bottoms —
not because every capitulation reverses, but because the ones that do
look like this.

##### GRINDING_TRAP (bold yellow)

```
GRINDING_TRAP px +0.42% 15m  CVD -0.15M  fund +0.0234%  OI +1.2% 15m
```

Fires when **all four** are true:
1. Price up ≥ 0.3% over last 15 minutes (`ALERT_PRICE_GRIND_PCT`)
2. 5m CVD ≤ 0 (no aggressive buying; could even be net selling)
3. Funding is positive (longs paying)
4. 15m OI delta > 0 (OI expanding)

Reads as: "price is climbing but nobody is actually buying aggressively
— the move is being walked up by positioning, not demand." Classic
fragile-top signature. Doesn't mean short it right here; means don't
chase the long.

### Alert-kind colors

From `_ALERT_STYLES` in `dashboard.py`:

| Kind | Color | Why |
|---|---|---|
| FUNDING | yellow | Caution / informational |
| LIQ_VOL | **bold red** | High-urgency — something just cascaded |
| OI_1H | magenta | Positioning context |
| CLUSTER | cyan | Geography — where stops are |
| LONG_SQUEEZE | **bold red** | Bearish setup (for longs) |
| CAPITULATION | **bold green** | Potential long entry (reversal setup) |
| GRINDING_TRAP | **bold yellow** | Fragile; don't chase |

Timestamps are dim. Symbols are bold white. Message bodies are plain
white.

---

## 8. Color legend — quick reference

The two most important things to remember:

**In most of the screener** (basis, OI deltas, liquidation counts), the
convention is conventional: **green = positive, red = negative**.

**In CVD and Taker%**, the convention is **inverted** for a sniping
lens: **red = crowded buying (warning), green = crowded selling
(potential reversal opportunity)**.

**In the "Top Cluster" column**, color encodes *strategic meaning*:

- red = clean resistance overhead (↑L)
- green = clean support below (↓S)
- yellow = cross-grain / unusual

**In the "Liq Clusters (1h)" panel**, color is just cohort:

- red = longs wiped there
- green = shorts wiped there

**Alert KIND colors** encode urgency and directional bias (see table
above).

---

## 9. How to use this for margin sniping

The dashboard is designed around the idea that single signals are
noisy, but *combinations* have real predictive value. Here are the
three canonical setups the composite alerts are designed to flag:

### Long squeeze setup (the LONG_SQUEEZE alert)

This setup is disabled by default on Hyperliquid until an all-market
liquidation source is wired in.

You're looking for a market where:
- Funding is bold red in the Funding% column
- OI Δ1h is solid green (leverage building)
- Taker% 5m is bold red (crowded buying)
- Top Cluster shows `↓L` (longs stacked below)

The theory: too many people are long, paying to be long, aggressively
adding to their longs, and there's a known stop zone below. If the
price can't make new highs to reward the positioning, mean-reversion
down through the cluster is the path of least resistance.

**What to watch for entry:** a failure to break higher combined with
CVD turning green (aggressive selling starting). The flush itself is
the snipe — your entry is *after* price takes out the cluster, as the
book rethickens.

### Capitulation reversal (the CAPITULATION alert)

This setup is disabled by default on Hyperliquid until an all-market
liquidation source is wired in.

You're looking for:
- Liq $ 5m in bold red (big-dollar liquidations)
- CVD 5m heavily negative AND **green** (remember the inversion)
- Taker% 5m bold green (≤ 30%)
- Basis% deeply red (perp trading at a discount to spot)

The theory: forced sellers are dumping the perp faster than arbitrageurs
can pull it back to spot. The perp discount is a measure of how
stressed the tape is. Historically, the biggest discounts mark
short-term bottoms.

**What to watch for entry:** basis starting to close back toward zero,
CVD flattening out (the sellers exhausting themselves). Cluster that
just formed becomes support on retest.

### Fade the grind (the GRINDING_TRAP alert)

You're looking for:
- Mark price drifting up
- CVD 5m flat or negative (red in value, colored green because it's
  negative — inversion!)
- Funding ticking up (not extreme yet)
- OI growing

The theory: nobody actually wants this rally. It's being walked up by
longs opening into a thin book. The first downtick unwinds it.

**What to watch:** this is the least precise of the three — the
"unwinding" can be anything from a 0.3% flush to a 5% dump. Best used
as a "don't chase" signal rather than an entry signal in itself.

### Sanity checks before acting on any setup

1. **Check Drift ms.** If it's yellow or red, your data is stale; don't
   trade off it.
2. **Cross-reference with BTC.** High-beta alts often just follow
   majors. A LONG_SQUEEZE on SOL while BTC is quietly making new highs
   is a different situation than one where BTC is also loaded.
3. **Are you the exit?** If a symbol has low notional (WIF on a slow
   day), even a "cluster" is only a handful of small positions. The
   best snipes are in mid-cap perps where cascades are real and liquid
   enough to exit quickly.
4. **This isn't backtested.** The composite setups are structurally
   motivated, not empirically optimized. Paper trade them first.

---

## 10. Tuning the thresholds

All thresholds live in `config.py`. Edit and restart.

| Setting | Default | Governs |
|---|---|---|
| `ALERT_FUNDING_PCT` | 0.10 | FUNDING alert + Funding% coloring |
| `ALERT_LIQ_VOL_5M_USD` | 2,000,000 | LIQ_VOL alert + Liq $ 5m coloring |
| `ALERT_OI_DELTA_1H_PCT` | 3.0 | OI_1H alert |
| `ALERT_TAKER_HIGH_PCT` | 60.0 | Taker% "crowded buying" threshold |
| `ALERT_TAKER_LOW_PCT` | 30.0 | Taker% "crowded selling" threshold |
| `ALERT_FUNDING_SQUEEZE_PCT` | 0.05 | LONG_SQUEEZE funding condition |
| `ALERT_CVD_SHARP_NEG_USD` | −500,000 | CAPITULATION CVD condition |
| `ALERT_BASIS_CAPITULATION` | −0.3 | CAPITULATION basis condition |
| `ALERT_LIQ_CAPITULATION_USD` | 500,000 | CAPITULATION liq volume condition |
| `ALERT_PRICE_GRIND_PCT` | 0.3 | GRINDING_TRAP 15m price condition |
| `LIQ_CLUSTER_BUCKET_PCT` | 0.1 | Width of price buckets for clustering |
| `LIQ_CLUSTER_MIN_COUNT` | 3 | Min events for default clustering |
| `LIQUIDATION_FEED_ENABLED` | False | Enables liquidation-dependent alerts after you add a feed |

**Smaller symbols need smaller thresholds.** The defaults are calibrated
for BTC/ETH-scale flow. For mid-cap Hyperliquid names, you may want to
lower CVD and OI thresholds after watching a few sessions. Liquidation
thresholds only matter after you add a liquidation source.

**If you're drowning in alerts**, widen the simple thresholds. If
you're not seeing anything on a quiet day, that's usually correct —
setups don't exist 24/7.

---

## 11. Honest limitations

Things this tool deliberately does not do, or does imperfectly:

- **No persistence.** When you quit, history is gone. Two weeks of
  logged data would make this a real research instrument; currently
  it's ephemeral. SQLite writer is a natural next step.
- **No official public all-market liquidation stream.** Hyperliquid's
  public market subscriptions provide trades and asset contexts, but not
  the Binance-style forced-order stream this dashboard previously used.
  Liquidation views are disabled unless you add another source.
- **No spot-side depth data.** The basis calculation uses Hyperliquid's
  oracle/reference price only. Knowing actual spot book depth would improve
  the capitulation signal.
- **CVD is taker-flow only.** Doesn't see maker-side accumulation.
- **OI is sampled at 60s for deltas.** Hyperliquid `activeAssetCtx`
  updates current OI faster, but the historical OI delta buffer is sampled
  once per minute to preserve meaningful 15m/1h windows.
- **Cluster bucketing depends on the mark.** Buckets are sized as 0.1%
  of the current mark — so in a fast-moving market, bucket boundaries
  shift, and a cluster that's "real" on a static chart may briefly
  dissolve in the live view.
