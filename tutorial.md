# sniper-streamer — Margin Sniping Tutorial

> **Disclaimer**: This tutorial is for educational purposes only. It explains how to read and interpret the `sniper-streamer` dashboard. Nothing here constitutes financial advice, a trading strategy recommendation, or a substitute for a licensed financial advisor. All trading decisions are yours alone.

---

## What Is Margin Sniping?

Margin sniping — sometimes called leverage hunting or liquidation sniping — is the practice of identifying markets where leveraged positions are structurally fragile and timing an entry to capture the acceleration that occurs when those positions are force-closed. When a leveraged position is liquidated, the exchange unwinds it at market, which pushes price further in the direction of the liquidation. If you are already positioned in that direction before the cascade begins, you can exit into that accelerated move.

Sniping is not about predicting price direction from first principles. It is about reading *crowding* — identifying when one side of a market has stacked on too much leverage, when the book is too thin to absorb a forced unwind, and when the flow conditions suggest the unwind is imminent.

`sniper-streamer` aggregates and processes various concurrent data points in a perpectual futures market to expose signals indicating the foregoing: 
1. Funding stress
2. Open interest build
3. Book thinness
4. Taker flow crowding
5. Composite alert conditions that combine 1-4.

### Background & Context

"Crowd" and "squeeze" are crucial to understand when trading crypto, especially because the crypto market heavily utilizes leverage (borrowing money to trade). 

#### "Crowded longs" is the setup; "long squeeze" is the event

1. **Crowded Longs (The Setup)**
    - When a trade is "crowded," it means an overwhelming majority of market participants are positioned on the same side of the market. 
    - In this case, they are "long," meaning they have bought an asset betting that the price will go up. 
    - When longs are crowded, the market becomes fragile for two main reasons:
        - **Exhausted Buying Power**: If everyone who wants to buy the asset has already bought it, there is a lack of new buyers left to step in and push the price higher. 
        - **Massive Sell Potential**: Every open "long" position is a future "sell" order. To exit a long position and take profits (or cut losses), the trader *must* sell the asset. Therefore, a crowded long market has a massive amount of latent sell pressure waiting to be triggered.

2. **The Long Squeeze (The Event)**
    - A "long squeeze" is a waterfall decline or cratering of asset price caused by those crowded long positions being forced to sell all at once. 
    - Because crypto traders frequently use leverage, their accounts have a "liquidation price." If the asset's price drops to this level, the exchange automatically steps in, closes the trader's position, and market-sells their assets to ensure the exchange doesn't lose borrowed money.

3. **How the Squeeze Happens**:
    1.  **Trigger**: Negative news published on the asset, whale sells a significant amount of asset, etc. → Causes an initial dip in asset price.
    2.  **First Domino**: Initial dip drives asset price down to liquidation levels of the most highly-leveraged long traders (e.g., those using 50x or 100x leverage). 
    3.  **Cascade**: The exchange forcibly sells off those traders' assets. This sudden flood of automated "sell" orders drives the price down even further.
    4.  **Long Squeeze**: This new, lower price now triggers the liquidation levels of the moderately-leveraged traders (e.g., 20x leverage), forcing the sale of their assets, which again pushes the asset price down, triggering liquidation of low-leverage traders (e.g., 10x leverage). And so on, effectively becoming a vicious cycle of cascading liquidation sales at progressively lower levels, with the price drop following liquidation at a higher level being the catalyst driving the price down to liquidate the positions at the next lowest leverage level.
    
**Thus, longs are "squeezed" out of their positions.**
    - **Crowded Longs**: A state of vulnerability. Too many people are betting the price will go up, creating a massive pool of potential sell-pressure.
    - **Long Squeeze**: The violent market reaction. The price drops, triggering forced liquidations, causing a rapid downward spiral in price. 

#### "Crowded shorts" is the setup on the opposite end of the market; "short squeeze" is the event at that same end

1. **Crowded Shorts (The Setup)**
    - When a market is "crowded with shorts," an overwhelming number of traders are betting that the price of the asset will go down while they hold borrowed shares that can then be sold at the lower price, enabling them to keep the difference between the asset price at the time borrowed minus the asset price at the time sold.
    - Mirroring the above-described crowded longs, the crowded shorts destablize the market:
        - **Exhausted Selling Power**: If everyone who wants to bet against the asset has already shorted it, there is very little natural selling pressure left to keep pushing the price down.
        - **Massive Buy Potential**: Every open "short" position is a guaranteed future "buy" order. A trader can only close a short position by buying back the asset, regardless whether to take a profit or stop a loss. A crowded short market is essentially a giant powder keg of latent buying pressure.

2. **Short Squeeze (The Event)**
    - A "short squeeze" is a parabolic move or gap up in price caused by those crowded short positions being forced to buy the asset all at once. 

3. **How the Squeeze Happens**:
    1.  **Trigger**: Suprise earnings report, improved or stablized fiscal situation, large share purchase, etc. → Causes unexpected and signficant jump in asset price. 
    2.  **First Domino**: As asset price rises, it reaches hits a liquidation price threshold (i.e., stop-loss trigger) at which the most highly-leveraged short sellers could not cover. 
    3.  **The Cascade**: Rising price puts the highest-leveraged short sellers underwater, which triggers the exchange to forcibly (automatically) *buy* asset from those highest-leveraged short sellers at market price. This sudden wave of buying (even though forced) drives asset price even higher.
    4.  **The Squeeze**: Reaching this even higher price subsequently triggers liquidations at the moderately-leveraged level of short sellers, which again drives up asset price to the next lower-leveraged short sellers until liquidation occurs at this lower-leveraged level, driving another cycle of asset price increase and subsequent short seller liquidation, and so on.  

**Thus, shorts are "squeezed" out of short positions**
    - Short sellers often attempt to buy back the asset before the price climbs any higher. The GameStop (GME) saga in 2021 is one example, but it happens routinely in the highly-leveraged crypto markets.
    - **Crowded Shorts**: Fragile market circumstance in which pressure from short sellers (i.e., betting on decline in an asset price) creates more future buy-pressure than the market can tolerate. 
    - **Short Squeeze**: Explosive event in which rising asset price triggers forced buy-backs, creating a rapid, self-perpetuating upward spiral of asset price.

---

## Dashboard Layout

The terminal is divided into three panels:

- **Main screener table** — one row per watchlist symbol, updated continuously
- **Alerts** (bottom-left) — recent threshold and composite alerts with timestamps
- **Flow Clusters (1h)** (bottom-right) — where aggressive taker volume has been concentrating over the past hour

Each panel is described in detail below.

---

## Main Screener Table

Each row is tied to a different perpetual contract being traded on Hyperliquid. The columns read left to right are a rough approximation of the logical progression of reasoning through a trade setup:
1. Where is the market?
2. What is the leverage state?
3. What is the flow doing?
4. How thick is the book?
5. How dependent is this asset on BTC?

### Symbol

The configured watchlist ticker for one asset (e.g., BTC-USDC).

### Mark $

- Current perpetual contract mark price
- Hyperliquid uses this when evaluating PnL and liquidation (Hyperliquid does **not** use last trade price)
- Mark price is derived from a smoothed index, not from actual trades on Hyperliquid

Because mark — not the trade tape — is what triggers liquidations, a divergence between the two is a timing signal. When actual trades are happening well above mark, leveraged longs are temporarily safer than their stated margin suggests: the liquidation engine is evaluating their positions against a lower number than where the market is really trading. The inverse is the more dangerous scenario for longs: when the trade tape has already fallen below mark, the mark will catch down, compressing long margins in a delayed wave even after the live tape has quieted. A downside cascade can therefore feel like it is "over" on the trade tape while the real liquidation pressure is still building as mark converges.

**How to detect a divergence on the dashboard**:

- **Flow Clusters panel** — the `##.##% away` distance field on each cluster line is the most direct indicator. A dominant flow cluster sitting 0.8%+ from mark in the direction of the flow means actual trading has moved materially beyond where mark is priced.
- **CVD vs. Mark $** — if CVD 1m/5m is strongly red (aggressive buying) but Mark $ has barely moved, mark is lagging the real upside move in the tape.
- **Drift C/T/B** — if Context drift (C) is stale while Trade drift (T) is fresh, mark has not yet updated to reflect recent activity. The gap between C and T age is a rough proxy for how out-of-sync mark currently is.

### 24h%

The percentage change in mark price relative to the previous day close published by Hyperliquid.

- **Green** — price is up over the past 24 hours
- **Red** — price is down over the past 24 hours

This is background context, not a primary signal. A large positive 24h% combined with crowded long indicators is a setup that has already run and may be exhausted. A large negative 24h% with crowded short indicators is likely over.

### Fund / FΔ1h

Two values separated by a `/`:

**Left — current funding rate** (per hour, displayed as a percentage):

Funding is the mechanism that keeps the perpetual contract price anchored to the index. When longs outnumber shorts, longs pay shorts. When shorts outnumber longs, shorts pay longs.

- **Bold red** — funding is significantly positive (longs are paying, longs are crowded). This is the primary fuel for a long squeeze.
- **Bold green** — funding is significantly negative (shorts are paying, shorts are crowded). This is the primary fuel for a short squeeze.
- **White** — funding is near zero, positioning is balanced.

The threshold for bold coloring is ±0.005% per hour (roughly ±0.12%/day, or about ±44%/year annualized). At that level, the cost of holding a leveraged position is high enough to accelerate the decision to close.

**Right — 1-hour funding delta** (how much the funding rate has changed in the past hour, in percentage points):

- **Red** — funding is rising (becoming more positive). Long crowding is building.
- **Green** — funding is falling (becoming more negative). Short crowding is building.
- **Dim** — no history yet, or no change.

The delta is often more actionable than the level. A moderate absolute funding rate that is accelerating upward means the crowding is still developing and the window may still be early.

### Basis% s/o

The difference between the perpetual mark price and the best available spot reference, expressed as a percentage. The suffix letter tells you which reference was used:

- **s** — true Hyperliquid spot price (preferred, more accurate)
- **o** — oracle price (fallback when no Hyperliquid spot market exists, or
  when spot basis is too far out of line with Hyperliquid's premium)

**Positive basis** — the perp is trading above spot. Longs are paying a premium; there is demand to be long via perp rather than spot.

**Negative basis** — the perp is trading below spot. Shorts have pushed the perp down relative to spot, or longs have abandoned it. A persistently negative basis combined with negative funding is a classic short-squeeze fuel — shorts are crowded *and* they have driven the price so far below spot that any mean reversion snaps back violently.

Spot basis is more useful than oracle basis because the oracle is time-smoothed.
When basis and premium diverge modestly, that divergence itself can be a signal.
When they diverge by more than the configured sanity limit, the dashboard falls
back to oracle basis so an illiquid or stale spot print does not dominate the
read.

### Prem%

Hyperliquid's own internal `premium` field, displayed alongside basis because it can diverge from the dashboard's direct mark-versus-reference calculation. Treat it as a second opinion. When basis and premium agree, the signal is more reliable.

### OI Δ15m%

The percentage change in open interest (total notional of all open contracts) over the past 15 minutes.

- **Rising OI + one-sided taker flow** — the core leverage-build signature. New leveraged positions are opening and they are predominantly on one side.
- **Falling OI** — positions are being closed or liquidated. Can signal a cascade in progress or positioning unwinding before one.
- **Flat OI with one-sided flow** — the flow is likely closing existing positions on one side while opening on the other, a rotation that is less explosive but still directional.

### OI/Vol

Open interest notional divided by 24-hour dollar volume.

This ratio measures how stale the leverage is relative to market activity. A market with $1B in OI and $5B in daily volume churns its open interest frequently — leveraged positions are getting closed and reopened regularly. A market with $1B in OI and $200M in daily volume has leverage that has been sitting for days.

- **Bold red** — OI/Vol ≥ 2.0×. High stale leverage. If price moves against these positions, the volume needed to unwind them is large relative to what the market normally handles. Forced unwinds can be very disorderly.
- **Yellow** — OI/Vol ≥ 1.0×. Elevated, worth watching.
- **Dim/white** — normal or low ratio.

High OI/Vol is not a trigger by itself — stale leverage can sit for a long time. It is an amplifier: when other conditions line up, a market with high OI/Vol tends to have a more violent unwind.

### σ15m

Realized volatility over the past 15 minutes, expressed as a percentage. This is the standard deviation of recent short-term returns scaled to a comparable unit.

- **Red** — σ15m ≥ 1.0%. The market is moving fast.
- **Yellow** — σ15m ≥ 0.5%. Elevated, worth noting.
- **Dim** — low, the market is quiet.

This column is used internally by the alert engine to normalize price-movement signals across different assets. A 0.3% price grind on BTC (low vol) is more significant than a 0.3% price grind on a high-vol alt that routinely moves 2% in 15 minutes. When you see σ15m elevated, the price-grind alert thresholds are harder to trigger; when it is low, the same absolute move looks more significant.

For margin sniping, a sudden spike in σ15m can mean a cascade has already started — or that something external has hit the market and is compressing or expanding vol in a way that changes the setup.

### CVD 1/5/15

Cumulative Volume Delta at three timeframes: 1 minute, 5 minutes, and 15 minutes. Each value is aggressive buy notional minus aggressive sell notional.

**Color convention is sniping-oriented, not directional**:

- **Red CVD** (positive value) — aggressive buyers are dominating. This signals crowded buying, which is fuel for a long squeeze (not a bullish signal for you to go long alongside).
- **Green CVD** (negative value) — aggressive sellers are dominating. This signals crowded selling, which is fuel for a short squeeze.
- **Dim** — balanced, no strong signal.

The three timeframes together form a stack that reveals momentum and exhaustion:

- **All three red** — sustained aggressive buying across all horizons. Long crowding is well established.
- **1m green but 5m and 15m still red** — the short horizon has just flipped. This is often the earliest signal that buying exhaustion is beginning, while the longer-horizon structure is still crowded long.
- **1m and 5m green but 15m still red** — exhaustion is developing over multiple minutes. The 15m structural crowding has not yet unwound.
- **All three green** — sustained aggressive selling. Short crowding is well established.

Watch the stack rolling over. The moment the shortest timeframe CVD flips while the longer ones remain crowded is often the earliest warning of an impending cascade.

### Taker5

The percentage of 5-minute taker notional that was aggressive buying (versus aggressive selling).

- **Bold red** ≥ 60% — strongly buy-dominated tape. Buyers are crowded.
- **Bold green** ≤ 30% — strongly sell-dominated tape. Sellers are crowded.
- **White** — balanced to mildly one-sided.

50% would be perfectly balanced. Values above 65% or below 35% indicate a market where essentially all aggressive participation is coming from one side.

### AvgTrd

Average trade notional over the past 5 minutes.

- **Yellow** — ≥ $50,000 average. Larger participants are involved.
- **White/dim** — small retail-sized trades.

Rising average trade size while the tape is one-sided suggests the crowding is not just retail noise — larger accounts are also pressing. This matters for magnitude: a liquidation cascade with large average positions tends to be sharper than one composed of small retail accounts.

### Book

Three components in one column: `spread / imbalance / [wall]`

**Spread** (basis points from top of book):

- **Red** — ≥ 5 bp. Very thin bid/ask spread suggests either low liquidity or a market-maker pulling quotes.
- **Yellow** — ≥ 2 bp. Elevated.
- **Dim** — tight spread, normal market conditions.

**Imbalance** (top-10 depth on bids versus asks):

- **Green** (positive) — more bid-side depth. Buyers have more resting orders. This is conventionally considered bullish but can also mean a large bid is temporarily propping price.
- **Red** (negative) — more ask-side depth. Sellers have more resting orders.
- **Dim** — balanced.

**Wall** (shown only when a single level is ≥ 2.5× average depth):

- Format: `B2.8x` or `A2.8x` — displayed in **yellow**
- A bid wall (`B`) can slow a downside move by absorbing selling pressure — until it is removed or hit through
- An ask wall (`A`) can cap upside — until it is lifted or swept

For margin sniping, a thinning spread combined with a shift from bid-heavy to ask-heavy imbalance while funding is elevated is an early-warning combination. The book is drying up on the side that would need to absorb forced selling.

### Impact

Hyperliquid's `impactPxs` width minus the natural top-of-book spread, in basis points. This is a thinness proxy: it measures how much a standardized meaningful order would slip *beyond* what the visible spread implies.

- **Bold red** — ≥ the symbol's threshold. The tuned defaults are 4 bps
  globally, with overrides for BTC (2 bps), BNB (3 bps), DOGE (8 bps), and ICP
  (13 bps). The book is thin. A forced unwind would cause material slippage.
- **Yellow** — ≥ half the threshold. Elevated thinness, building toward alert territory.
- **Dim** — normal depth.

High impact excess is critical for sizing the risk in a sniping trade. If impact excess is high when a cascade starts, the price move will be larger and faster because there are fewer resting orders to absorb each wave of liquidations. This is good for a well-timed snipe and catastrophic for a position on the wrong side.

### Flow Clus

The single largest 1-hour aggressive taker-flow price bucket, summarized in one field:

```
0.42% ↑B $1.20M
```

- **0.42%** — the bucket's distance from the current mark price
- **↑** — the cluster is above the current mark price
- **B** — buy-notional dominated (B = buy, S = sell)
- **$1.20M** — total notional in this price bucket

**Color conventions**:

- **Red** — buy cluster above mark (`↑B`). Aggressive buyers concentrated at a price above current. Can act as a retest target or resistance.
- **Green** — sell cluster below mark (`↓S`). Aggressive sellers concentrated below current price. Can act as support or a reversal zone.
- **Dim** — other combinations (buy cluster below mark, or sell cluster above mark) — directionally mixed.

Flow clusters are not stop-loss clusters. They show where actual aggressive trading happened, which can create magnet effects (price retesting a high-volume node) or reversal zones (exhaustion near a prior high-volume sell cluster).

### β/ρ BTC

Two values: BTC beta and BTC return correlation over recent history.

- **Beta** — how much this asset moves per unit of BTC move (e.g., 1.4 means it moves 1.4% when BTC moves 1%)
- **ρ (rho)** — correlation coefficient (-1 to +1) of 1-minute returns

**Color**:

- **Red** — high correlation (≥ 0.6). The asset is moving largely with BTC. A squeeze in this asset may be partially explained by BTC.
- **Green** — low correlation (≤ 0.2). The asset is moving independently. A squeeze here is idiosyncratic — and often more violent.
- **White** — moderate correlation.

A high-beta, low-correlation asset is particularly interesting: it amplifies BTC moves when correlated but can also move violently on its own crowding dynamics. When you see a squeeze setup forming on a low-correlation asset while BTC is flat, that is a purer signal.

### Drift C/T/B

Data age for three streams: Context / Trades / Book

- **C** — time since last mark/OI context update
- **T** — time since last trade
- **B** — time since last book update

**Colors**:

- **Red** — > 5 seconds. Data may be stale.
- **Yellow** — > 2 seconds. Lagging.
- **Dim** — fresh data.

A stale trade feed (`T` in red) means the CVD, Taker5, and AvgTrd values are not reflecting the current tape. During a cascade, the trade feed should be actively updating. If `T` goes red while other feeds are fresh, be cautious about acting on CVD or taker% values.

---

## Alerts Panel (Bottom-Left)

Displays up to 10 recent alerts. Each line:

```
[HH:MM:SS]  SYMBOL  ALERT_KIND  details
```

Alerts are deduplicated: most symbol/kind pairs will not re-fire within a
5-minute window. Flow-cluster alerts use a longer side-level dedupe window
because the visible cluster panel can keep showing the same high-volume node for
an hour.

### Simple Alerts

These fire when a single threshold is breached.

**FUNDING** — yellow

Fires when the absolute funding rate exceeds 0.005%/hr (≈ 0.12%/day). Either positive or negative. This is the lowest-bar alert — it signals that positioning has moved to a level where it is costing leveraged holders meaningfully. It is necessary but not sufficient for a squeeze setup.

**OI_1H** — magenta

Fires when 1-hour open interest has changed by more than 0.75%. A rapid OI surge means new leveraged positions opened at scale in a short window. Combined with directional taker flow, this tells you who opened them. Combined with thin book, it tells you the unwind could be disorderly.

**THIN_BOOK** — bold red

Fires when impact excess exceeds the symbol's threshold. A thin book by itself is not a setup — thinness is structural in some markets. But thin book combined with elevated funding, rising OI, and one-sided flow means any forced unwind will have minimal cushion.

**FLOW_CLUSTER** — cyan

Fires when the largest taker-flow price bucket exceeds the stricter alert-only
volume-scaled notional threshold, has enough trades, and is at least 70%
one-sided. This is the taker-flow analog to a liquidation cluster — a price zone
where a large amount of aggressive trading has concentrated. The bottom-right
panel can still show smaller clusters for context; the alert is reserved for
material, directional clusters.

### Composite Alerts

These fire when multiple conditions align simultaneously. They are the primary actionable signals.

**LONG_SQUEEZE** — bold red

All of the following must be true:
- Funding is positive at or above the squeeze threshold
- OI is rising (new longs are still opening or net buying is occurring)
- The tape is crowded with buyers (taker% ≥ ~60%)
- The book is thin or ask-heavy (Impact or imbalance condition)

This alert says: longs are crowded, more longs keep opening, the book cannot absorb a forced unwind, and taker flow confirms the crowding. The setup is loaded for a downside cascade if price reverses and the weakest longs start getting liquidated.

**SHORT_SQUEEZE** — bold green

All of the following must be true:
- Funding is negative at or below the squeeze threshold
- OI is rising
- Taker flow is sell-dominated (sellers are crowded)
- Perp is trading below spot (negative basis)

This alert says: shorts are crowded, they have pushed the perp below spot, more shorts keep opening, and the setup is fragile for a violent short-covering rally if price moves up even modestly.

**CAPITULATION** — bold green

All of the following must be true:
- Aggressive sell CVD has been sharp and negative over 5 minutes
- Taker% is low (sellers still crowded)
- Perp is trading below spot (basis negative)
- Book impact is elevated (the book is thin)

This alert identifies forced selling into a thin book. The selling is not organized — it looks like liquidation-driven unloading. A CAPITULATION alert can mark the exhaustion point of a downside move, where all the weak longs have been forced out and the market is ready to mean-revert upward. Going long into capitulation is higher risk than going long before a cascade (because the move has already happened), but the reversal can also be sharp.

**GRINDING_TRAP** — bold yellow

All of the following must be true:
- Price is rising at least 1.5 standard deviations (in σ15m terms) over 15 minutes
- CVD is flat or negative (buying is not actually driving the price up)
- Funding is rising
- OI is expanding

This is a structural warning rather than an immediate trigger. Price is grinding up, but there is no real aggressive buying behind it — CVD would be positive if buyers were driving it. Instead, the price is rising because sellers are pulling their asks (a thin book rising) while funding and OI build. This is the setup most likely to reverse sharply when the last buyer exhausts. The GRINDING_TRAP alert says "this move is fragile — funding is rising, longs are building, but no one is actually chasing it aggressively."

---

## Flow Clusters Panel (Bottom-Right) — "Flow Clusters (1h)"

This panel shows the top two taker-flow clusters per symbol from the past hour. Each line:

```
SYMBOL  ↑/↓  B/S  @ price   ##.##% away   x#  $####   bucket 0.#%
```

**Symbol** — bold white label for the asset

**Arrow (↑ or ↓)**:
- `↑` — the cluster is *above* the current mark price
- `↓` — the cluster is *below* the current mark price

**B or S**:
- `B` (Buy) — buy notional exceeded sell notional in this price bucket
- `S` (Sell) — sell notional exceeded buy notional in this price bucket

**Combined color of the arrow + letter**:
- **Red** (`↑B`) — a buy-dominated cluster sits *above* current price. Aggressive buyers have been accumulating at a level the market has not yet sustained. This can act as a resistance test zone or, if broken, a retest magnet.
- **Green** (`↓S`) — a sell-dominated cluster sits *below* current price. Aggressive sellers have been active at a lower level. This can act as support (if the sellers were stop-hunters and are now done) or as a re-entry zone for fresh shorts.
- **Yellow/dim** — other combinations (buy cluster below, or sell cluster above) — directionally ambiguous, less immediately actionable.

**`##.##% away`** — how far the cluster price is from the current mark, as a percentage. Shown in dim style. This tells you how much price would need to move to reach that zone of prior aggressive activity.

**`x#`** — the number of individual aggressive trades that were aggregated into this bucket. More trades means more participants touched this level. A cluster with x50 trades is more meaningful than one with x4.

**`$####`** — the total notional (in USD, using short format: k, M, B) in this price bucket. The size of the cluster reflects how much conviction was placed at this level.

**`bucket 0.#%`** — the width of the price bucket used to aggregate trades, shown in dim style. Bucket width is dynamically calculated as 0.25× the 15-minute realized volatility, clamped between 0.1% and 0.6%. Higher-volatility assets have wider buckets; lower-volatility assets have narrower buckets. This normalization means a cluster on BTC (low vol) represents a tighter price zone than a cluster on a high-vol alt.

**How to use flow clusters**:

Clusters are not stop-loss maps. They show where real trading happened — which means they can function as:

- **Magnet levels** — price often retests zones of prior high-volume activity
- **Exhaustion markers** — a large sell cluster that formed during a downswing may represent where most of the selling was done; once price returns to that level, sellers may be exhausted
- **Conviction zones** — when a cluster forms at a level that price has been unable to break through, that level has shown resistance or support in realized flow terms, not just technically

In a squeeze context, a large buy cluster forming just above current price while funding is already elevated tells you longs are piling in above current mark — which is potential resistance and also means those positions are thin on margin before they become profitable. A sharp reversal would put all of them underwater quickly.

---

## Example Scenarios

---

### Example 1 — Short Side: Riding a Long Squeeze

**Setup goal**: Enter short before a leveraged long cascade unwinds.

---

**Step 1: Initial trigger — LONG_SQUEEZE alert fires**

The Alerts panel shows:

```
[14:32:11]  SOL-USDC  LONG_SQUEEZE  fund=+0.012%/hr oi_delta=+2.1% taker%=67
```

This composite alert tells you multiple conditions are simultaneously true: funding is elevated (longs are paying), OI has been rising (new longs are still opening), and the taker tape is crowded with buyers. This is your first reason to look at SOL closely.

---

**Step 2: Scan the main table row for supporting data**

Look at the SOL row and check each relevant column:

**Fund/FΔ1h**: `+0.012% / ↑+0.004%` in bold red — funding is not just elevated, it has been *rising* over the past hour. The crowding is still developing.

**OI Δ15m%**: `+1.8%` — open interest surged in the past 15 minutes. New leveraged longs are still being opened right now.

**OI/Vol**: `1.8×` in yellow — borderline high. There is a meaningful amount of stale leverage relative to daily volume.

**CVD 1/5/15**: Red across all three timeframes — `+$2.1M / +$8.4M / +$22M`. Sustained aggressive buying across every timeframe. The crowd has been consistently buying.

**Taker5**: `68%` in bold red — more than two-thirds of recent notional has been aggressive buyers.

**Book**: `4.2bp / −18% / A2.1x` — the spread is elevated (4.2bp), the book is ask-heavy (−18% imbalance means more asks than bids), and there is a resting ask wall at 2.1× average depth. The book is not particularly supportive of upside.

**Impact**: Bold red — impact excess is above the threshold. A forced unwind would cause real slippage.

**β/ρ BTC**: `β=0.9 / ρ=0.18` in green — low BTC correlation. This setup is largely idiosyncratic to SOL, not just BTC dragging it around.

All of these are consistent and reinforcing. This is a high-quality setup.

---

**Step 3: Check the Flow Clusters panel for structure**

```
SOL  ↑B  @ 148.32   +0.41% away   x38  $1.8M   bucket 0.21%
SOL  ↓S  @ 145.10   −1.78% away   x12  $420k   bucket 0.21%
```

The dominant cluster is buy-side, sitting 0.41% above current mark. Longs have been aggressively buying just above where price is now. This means the crowd is already extended slightly upward. The sell cluster below is smaller and further away.

This tells you the longs are piled in above the current level with relatively little sell-side support below them. If price drops even modestly, those above-mark buy clusters are now underwater and their stop-losses or margin calls start triggering.

---

**Step 4: Look for what would *not* support this trade**

Before entering, check what would undermine the thesis:

- **If σ15m were spiking red** (> 1.0%) — a cascade may have already started and you would be entering mid-move with less edge
- **If BTC correlation were high (ρ > 0.6 in red)** — the move might be explained by BTC lifting, not idiosyncratic crowding. Check if BTC funding is also elevated.
- **If OI were falling instead of rising** — positions are closing, not building. The trigger may have already fired.
- **If the book showed a large bid wall (B3.0x)** — a large buyer is defending a level. This can temporarily prevent a cascade even when other signals line up.
- **If the CVD 1m were flipping green while 5m/15m stay red** — short-horizon exhaustion is appearing. This can either be the first signal of a roll, or just noise. Wait to see if the 5m follows.

None of those are present in this example. Proceed to evaluate entry.

---

**Step 5: Managing the position after entry**

You are short. The cascade you anticipated either develops quickly or it does not. Watch:

**What to watch most vigilantly**:

1. **Fund/FΔ1h right column (delta)**: If the delta turns green (funding is now falling), longs are covering and the short-side fuel is dissipating. This can mean the cascade happened and is fading — consider taking profit.

2. **OI Δ15m%**: If OI starts falling sharply, positions are being closed — the liquidations are happening. This is your confirmation. If OI instead flattens or reverses upward, the cascade did not trigger.

3. **CVD 1m**: The first timeframe to flip. If the 1-minute CVD flips from red to green (net selling appearing), the buying is exhausting. This is often the first real-time confirmation that the cascade is starting.

4. **Taker5**: Should drop sharply when liquidations hit — forced sells dominate. If taker% stays above 55%, longs are not being closed in size yet.

---

**Indicators that the position should be closed immediately**:

- **CAPITULATION alert fires** — the sell cascade has reached the exhaustion stage. The forced selling is late-stage, not early. If you entered early and rode this, the alert is your exit signal.
- **CVD 1m and 5m both flip green and are deepening** — selling is accelerating but OI is also falling fast, meaning liq cascade is advanced.
- **SHORT_SQUEEZE alert fires for the same symbol** — conditions have flipped. The market has moved so far down that shorts (yours included) are now at risk.
- **Basis turns sharply positive** — perp is now trading above spot, meaning buyers have returned and the unwind may be over.
- **Book imbalance flips from negative (ask-heavy) to positive (bid-heavy)** — buyers are stepping back in at the book level.

These indicators are often concurrent: a CAPITULATION alert usually fires alongside a CVD flip, a rising book imbalance, and a basis reversal. When you see two or more of them at once, exit quickly — the move is done.

---

### Example 2 — Long Side: Riding a Short Squeeze

**Setup goal**: Enter long before a crowded short position unwinds in a covering rally.

---

**Step 1: Initial trigger — SHORT_SQUEEZE alert fires**

The Alerts panel shows:

```
[09:14:44]  ETH-USDC  SHORT_SQUEEZE  fund=−0.009%/hr oi_delta=+1.4% taker%=28 basis=−0.31%
```

Funding is deeply negative (shorts are paying longs), OI is rising (new shorts are still opening), the tape is sell-dominated (28% taker buy = 72% aggressive selling), and the perp is trading 0.31% below spot. This is the short-squeeze fuel stack: shorts are crowded, they have driven the perp below spot, and they are still pressing.

---

**Step 2: Scan the main table row**

**Fund/FΔ1h**: `−0.009% / ↓−0.003%` in bold green — funding is already negative and getting *more* negative. Shorts are being added continuously.

**Basis% s**: `−0.31% (s)` — the perp is 0.31% below Hyperliquid spot. This is meaningful: arbitrageurs and spot holders have an incentive to sell spot and buy perp to capture this basis, which mechanically bids the perp back up toward spot. The more negative basis becomes, the stronger that mean-reversion pull.

**OI Δ15m%**: `+2.3%` — open interest is still rising rapidly. New short positions are opening.

**CVD 1/5/15**: Green across all timeframes — `−$1.8M / −$7.2M / −$19M`. Aggressive sellers have dominated every timeframe. The crowd has been consistently selling.

**Taker5**: `26%` in bold green — aggressive buying is almost absent. Nearly all aggressive participation has been selling.

**Book**: `3.8bp / +22% / B1.9x` — the book is bid-heavy (more resting bids than asks, +22% imbalance). Despite the aggressive selling, there are more limit-buy orders sitting than limit-sell orders. This is a divergence: the active traders are selling aggressively while the passive book is supporting bids. This is often a sign that the aggressive sellers are running out of willing passive counterparties.

**Impact**: Yellow — elevated thinness, not yet at alert threshold but notable.

**β/ρ BTC**: `β=1.2 / ρ=0.14` — low BTC correlation. ETH is moving on its own dynamics, not BTC drag.

---

**Step 3: Check Flow Clusters for structural context**

```
ETH  ↓S  @ 3,242.10   −0.88% away   x61  $4.2M   bucket 0.18%
ETH  ↑B  @ 3,298.40   +0.71% away   x19  $1.1M   bucket 0.18%
```

The dominant cluster is a large sell cluster sitting 0.88% below current mark. $4.2M in aggressive selling happened at that level. This cluster tells you two things: (1) there was significant short commitment at 3,242 — those are positions now sitting underwater if price rises to current levels; and (2) a retest of that level is likely to encounter resistance from existing shorts defending their entries.

The smaller buy cluster above (+0.71%) is less relevant here.

The key insight: if price moves upward from here, the crowd of shorts who entered at 3,242 will see their positions approach breakeven. If they are leveraged, their margin cushion shrinks fast. At some point, covering orders start going in.

---

**Step 4: Look for what would *not* support this trade**

- **If basis were positive** — the perp is not below spot, so there is no mean-reversion mechanical pressure. The short-squeeze setup requires perp below spot.
- **If OI were falling** — shorts are already covering, the move may have started without you.
- **If the book were ask-heavy despite funding being negative** — passive sellers are willing to provide supply, which dampens the squeeze. The book in this example is bid-heavy, which is supportive.
- **If BTC were also showing elevated negative funding** — this might be a BTC-correlated macro sell-off, not an idiosyncratic ETH short squeeze. Check β/ρ BTC.
- **If σ15m were already > 1.0% (red)** — volatility is already spiking. The covering rally may have started and you are entering late into an already-moving market.

---

**Step 5: Managing the position after entry**

You are long. The short squeeze either fires or the shorts are patient enough to avoid triggering it. Watch:

**What to watch most vigilantly**:

1. **Basis%**: If basis moves from −0.31% toward 0% or positive, spot-perp arbitrage and natural buying are working. This is directional confirmation.

2. **Fund/FΔ1h delta**: If the funding delta turns red (funding moving from negative toward zero), shorts are covering. The squeeze is progressing.

3. **CVD 1m**: When the 1-minute CVD flips from green to red, aggressive buying is appearing. This is the real-time confirmation that the covering rally has begun — shorts are no longer pressing and buyers are now the aggressive side.

4. **Taker5**: Rising from 26% toward 40-50% confirms buying is returning. A jump above 55% is strong confirmation.

---

**Indicators that the position should be closed immediately**:

- **LONG_SQUEEZE alert fires for ETH** — the situation has completely inverted. The covering rally overshot and now longs are crowded. This is a hard exit signal.
- **CVD 1m flips back to green after spiking red** — the covering rally stalled. Aggressive selling is returning.
- **Basis turns sharply positive** (perp now above spot) — the mean-reversion that fueled the squeeze is now working against you in the other direction.
- **OI is rising again while CVD is red** — new shorts are opening at the higher price. The squeeze may be over and the market is re-pressing short.
- **GRINDING_TRAP alert fires** — if price has risen but CVD is now flat or negative, the move may be a weak grind without real covering demand. The fragility alert means the up-move could reverse.

As with the short example, multiple indicators often appear together at turning points. Basis turning positive, CVD flipping green, and a LONG_SQUEEZE alert arriving in quick succession are collectively a strong signal to exit.

---

## Quick Reference: Signal Hierarchy for Margin Sniping

Not all signals are equal. Here is a rough priority order for building a thesis:

1. **Composite alert fires** (LONG_SQUEEZE, SHORT_SQUEEZE, CAPITULATION, GRINDING_TRAP) — necessary condition for a high-quality setup
2. **CVD stack** — confirms which side is crowded and whether exhaustion is appearing
3. **Funding level and delta** — confirms crowding and whether it is building or fading
4. **Basis** — confirms the perp-vs-spot dislocation that feeds a squeeze
5. **OI Δ15m%** — confirms whether new leverage is still entering
6. **Impact / Book** — confirms the structural thinness that amplifies the cascade
7. **Flow Clusters** — confirms where prior conviction sits and whether those levels are being defended or abandoned
8. **OI/Vol** — provides context on how stale the leverage is (amplifier, not trigger)
9. **β/ρ BTC** — distinguishes idiosyncratic setups from BTC-driven moves

A setup with only one or two of these signals is noise. A setup where five or six of them align is worth your full attention.

---

## Operational Notes

**Wait for history to build.** OI deltas, funding velocity, realized vol, and BTC beta need runtime history before they are meaningful. The columns will show dim or missing values in the first few minutes after launch. Wait at least 15–30 minutes before relying on σ15m, CVD stacks, or β/ρ.

**Impact thresholds are symbol-aware.** The 2026-04-25 retained run showed that
BTC, BNB, DOGE, and ICP need different impact baselines. ICP remains overridden
to 13 bps because its structural impact excess is high; BTC is overridden lower
because a 2 bp impact excess is already unusual there. Treat a THIN_BOOK alert
as a symbol-relative thinness event, not a raw cross-asset comparison.

**Stale drift is an early warning.** If the Drift C/T/B column shows a stale trade feed (T in red) while other feeds are current, do not act on CVD or taker% values — they are not reflecting the current tape. During a cascade, the trade feed should be the most active stream.

**Tuning thresholds.** The defaults in `config.py` are starting points. After watching the dashboard for a session across different market conditions, you will notice which assets trigger alerts too frequently (reduce thresholds) and which seem quiet even when visually there is crowding (increase sensitivity). Use the export script to review historical alert distributions and metric ranges before tightening.
