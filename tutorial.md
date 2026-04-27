# sniper-streamer — Margin Sniping Tutorial

---

## 1. Core Concept

Margin sniping means positioning _before_ leveraged traders get force-liquidated, then riding the cascade resulting from the liquidations.

When a leveraged position is liquidated, the exchange closes it at MARKet. That forced order pushes price further in the liquidation's direction, which liquidates more positions, which pushes price further — a self-reinforcing cascade. If you are already positioned in that direction, you exit into the accelerated move.

Sniping does not predict price direction. It reads **crowding**: which side has stacked too much leverage, whether the order book can absorb a forced unwind, and whether flow conditions suggest the unwind is imminent.

### 1.1 The Setup → Event Pattern

Every squeeze follows the same structure regardless of direction:

1. **Crowding** (setup): One side of the MARKet is over-positioned. Exhausted buying/selling power means no new participants can push price further. Every open position on the crowded side is latent pressure in the _opposite_direction — longs must eventually sell; shorts must eventually buy.
 
2. **Trigger**: Any adverse price move — news, a whale order, a correlated asset moving.
 
3. **Cascade** (event): The trigger liquidates the most highly-leveraged positions. Those forced closes push price further, liquidating the next leverage tier, and so on. Each wave feeds the next.
 

- **Long squeeze**: Longs are crowded → price dips → forced _selling_ cascades downward. 
- **Short squeeze**: Shorts are crowded → price rises → forced _buying_ cascades upward.

Dashboard shows setups (e.g., crowding, thin books, one-sided flow) for pre-event MARKet entry.

---

## Dashboard Layout

The terminal is divided into three panels:

- **Main screener table**: one row per watchlist symbol, updated continuously
- **Alerts**: (bottom-left) recent threshold and composite alerts with timestamps
- **Liq Clusters (1h)**: (bottom-right) where Bybit liquidation events are stacking by price

---

## Main Screener Table

Each row approximates a logical progression of reasoning through a trade setup:
1. Where is the market?
2. What is the leverage state?
3. What is the flow doing?
4. How thick is the book?
5. How dependent is this asset on BTC?

### Symbol

The configured watchlist ticker for one asset (e.g., BTC-USDC).

### Mark $ (MARK)

- Current perpetual contract MARK 
- Hyperliquid uses this when evaluating PnL and liquidation (Hyperliquid does **not** use last trade $)
- MARK is derived from a smoothed index, not from actual trades on Hyperliquid
- MARK triggers liquidation, not trade $
- Divergence between the MARK and TRADE PRICE means liquidation risk is tempoarily wrong. Use as timing signal. 
    - To detect MARK/TRADE PRICE divergence:
        - **CVD vs. MARK**: if CVD 1m/5m is strongly red (aggressive buying) but MARK has barely moved, MARK lagging behind upside price move.
        - **Drift C/T/B**: if Context drift (C) is stale while Trade drift (T) is fresh, MARK has not yet updated to reflect recent activity. C-T gap is rough proxy for how out-of-sync MARK is.
        - **Liq Clusters panel**: `##.##% away` field on each cluster line shows where forced closes are occurring relative to MARK. 
            - Large cluster far from MARK indicates liquidation has already occured on the other market (ByBit). Hyperliquid is lagging but will catch down or up. 

### 24h%

The percentage change in MARK relative to the previous day close published by Hyperliquid.

- **Green**: price is up over the past 24 hours
- **Red**: price is down over the past 24 hours

This is background context, not a primary signal. A large positive 24h% combined with crowded long indicators is a setup that has already run and may be exhausted. A large negative 24h% with crowded short indicators is likely over.

### Fund / FΔ1h

Two values separated by a `/`:

**Left — current funding rate** (per hour, displayed as a percentage):

Funding is the mechanism that keeps the perpetual contract price anchored to the index. When longs outnumber shorts, longs pay shorts. When shorts outnumber longs, shorts pay longs.

- **Bold red**: funding is significantly positive (longs are paying, longs are crowded). This is the primary fuel for a long squeeze.
- **Bold green**: funding is significantly negative (shorts are paying, shorts are crowded). This is the primary fuel for a short squeeze.
- **White**: funding is near zero, positioning is balanced.

The threshold for bold coloring is ±0.00125% per hour. In the latest retained
Hyperliquid run, that was the repeated hot-funding plateau. At that level, the
cost of holding a leveraged position is high enough to treat funding as crowding
context, but it is still not a standalone trade signal.

**Right — 1-hour funding delta** (how much the funding rate has changed in the past hour, in percentage points):

- **Red**: funding is rising (becoming more positive). LONG ↑.
- **Green**: funding is falling (becoming more negative). SHORT ↑.
- **Dim**: No information.

The delta is often more actionable than the level. A moderate absolute funding rate that is accelerating upward means the crowding is still developing and the window may still be early.

### Basis%

The difference between the perpetual MARK $ and the best available spot reference, expressed as a percentage. No suffix means the dashboard used true Hyperliquid spot, which is the preferred basis reference.

- **No suffix**: true Hyperliquid spot price (preferred, more accurate)
- **o**: oracle price (fallback when no Hyperliquid spot MARKet exists, or
 when spot basis is too far out of line with Hyperliquid's premium)

**Positive basis**: the perp is trading above spot. Longs are paying a premium; there is demand to be long via perp rather than spot.

**Negative basis**: the perp is trading below spot. Shorts have pushed the perp down relative to spot, or longs have abandoned it. A persistently negative basis combined with negative funding is a classic short-squeeze fuel — shorts are crowded *and* they have driven the price so far below spot that any mean reversion snaps back violently.

Spot basis is more useful than oracle basis because the oracle is time-smoothed.
When basis and premium diverge modestly, that divergence itself can be a signal.
When they diverge by more than the configured sanity limit, the dashboard falls
back to oracle basis so an illiquid or stale spot print does not dominate the
read.

### Prem%

Hyperliquid's own internal `premium` field, displayed alongside basis because it can diverge from the dashboard's direct MARK-versus-reference calculation. Treat it as a second opinion. When basis and premium agree, the signal is more reliable.

### OI Δ15m%

The percentage change in open interest (total notional of all open contracts) over the past 15 minutes.

- **Rising OI + one-sided taker flow**: the core leverage-build signature. New leveraged positions are opening and they are predominantly on one side.
- **Falling OI**: positions are being closed or liquidated. Can signal a cascade in progress or positioning unwinding before one.
- **Flat OI with one-sided flow**: the flow is likely closing existing positions on one side while opening on the other, a rotation that is less explosive but still directional.

### OI/Vol

Open interest notional divided by 24-hour dollar volume.

This ratio measures how stale the leverage is relative to MARKet activity. A MARKet with $1B in OI and $5B in daily volume churns its open interest frequently — leveraged positions are getting closed and reopened regularly. A MARKet with $1B in OI and $200M in daily volume has leverage that has been sitting for days.

- **Bold red**: OI/Vol ≥ 2.0×. High stale leverage. If price moves against these positions, the volume needed to unwind them is large relative to what the MARKet normally handles. Forced unwinds can be very disorderly.
- **Yellow**: OI/Vol ≥ 1.0×. Elevated, worth watching.
- **Dim/white**: normal or low ratio.

High OI/Vol is not a trigger by itself — stale leverage can sit for a long time. It is an amplifier: when other conditions line up, a MARKet with high OI/Vol tends to have a more violent unwind.

### σ15m

Realized volatility over the past 15 minutes, expressed as a percentage. This is the standard deviation of recent short-term returns scaled to a comparable unit.

- **Red**: σ15m ≥ 1.0%. The MARKet is moving fast.
- **Yellow**: σ15m ≥ 0.5%. Elevated, worth noting.
- **Dim**: low, the MARKet is quiet.

This column is used internally by the alert engine to normalize price-movement signals across different assets. A 0.3% price grind on BTC (low vol) is more significant than a 0.3% price grind on a high-vol alt that routinely moves 2% in 15 minutes. When you see σ15m elevated, the price-grind alert thresholds are harder to trigger; when it is low, the same absolute move looks more significant.

For margin sniping, a sudden spike in σ15m can mean a cascade has already started — or that something external has hit the MARKet and is compressing or expanding vol in a way that changes the setup.

### CVD 1/5/15

Cumulative Volume Delta at three timeframes: 1 minute, 5 minutes, and 15 minutes. Each value is aggressive buy notional minus aggressive sell notional.

**Color convention is sniping-oriented, not directional**:

- **Red CVD** (positive value) — aggressive buyers are dominating. This signals crowded buying, which is fuel for a long squeeze (not a bullish signal for you to go long alongside).
- **Green CVD** (negative value) — aggressive sellers are dominating. This signals crowded selling, which is fuel for a short squeeze.
- **Dim**: balanced, no strong signal.

The three timeframes together form a stack that reveals momentum and exhaustion:

- **All three red**: sustained aggressive buying across all horizons. Long crowding is well established.
- **1m green but 5m and 15m still red**: the short horizon has just flipped. This is often the earliest signal that buying exhaustion is beginning, while the longer-horizon structure is still crowded long.
- **1m and 5m green but 15m still red**: exhaustion is developing over multiple minutes. The 15m structural crowding has not yet unwound.
- **All three green**: sustained aggressive selling. Short crowding is well established.

Watch the stack rolling over. The moment the shortest timeframe CVD flips while the longer ones remain crowded is often the earliest warning of an impending cascade.

### Taker5

The percentage of 5-minute taker notional that was aggressive buying (versus aggressive selling).

- **Bold red** ≥ 60% — strongly buy-dominated tape. Buyers are crowded.
- **Bold green** ≤ 30% — strongly sell-dominated tape. Sellers are crowded.
- **White**: balanced to mildly one-sided.

50% would be perfectly balanced. Values above 65% or below 35% indicate a MARKet where essentially all aggressive participation is coming from one side.

### AvgTrd

Average trade notional over the past 5 minutes.

- **Yellow**: ≥ $50,000 average. Larger participants are involved.
- **White/dim**: small retail-sized trades.

Rising average trade size while the tape is one-sided suggests the crowding is not just retail noise — larger accounts are also pressing. This matters for magnitude: a liquidation cascade with large average positions tends to be sharper than one composed of small retail accounts.

### Book

Three components in one column: `spread / imbalance / [wall]`

**Spread** (basis points from top of book):

- **Red**: ≥ 5 bp. Very thin bid/ask spread suggests either low liquidity or a MARKet-maker pulling quotes.
- **Yellow**: ≥ 2 bp. Elevated.
- **Dim**: tight spread, normal MARKet conditions.

**Imbalance** (top-10 depth on bids versus asks):

- **Green** (positive) — more bid-side depth. Buyers have more resting orders. This is conventionally considered bullish but can also mean a large bid is temporarily propping price.
- **Red** (negative) — more ask-side depth. Sellers have more resting orders.
- **Dim**: balanced.

**Wall** (shown only when a single level is ≥ 2.5× average depth):

- Format: `B2.8x` or `A2.8x` — displayed in **yellow**
- A bid wall (`B`) can slow a downside move by absorbing selling pressure — until it is removed or hit through
- An ask wall (`A`) can cap upside — until it is lifted or swept

For margin sniping, a thinning spread combined with a shift from bid-heavy to ask-heavy imbalance while funding is elevated is an early-warning combination. The book is drying up on the side that would need to absorb forced selling.

### Impact

- Hyperliquid's `impactPxs` width minus the natural top-of-book spread, in basis points. This is a thinness proxy: it measures how much a standardized meaningful order would slip *beyond* what the visible spread implies.
- Impact excess ≈ (price impact of a typical sized order) − (visible bid/ask spread)
 - Spread is baseline friction (always get paid)
- Metric isolates hidden illiquidity not visible in the spread. Use to track how much worse execution gets when surpassing top-of-book liquidity.
 - ↑ impact excess on cascade start, price move will be larger and faster because fewer resting orders to absorb each wave of liquidations. 
 - Good if snipe move is well-timed only.

- Color:
 - **Bold red**: ≥ the symbol's threshold. 
 - The book is thin. A forced unwind would cause material slippage.
 - Defaults to 4 bps, with overrides for BTC (2 bps), DOGE (2.5 bps), and XRP (2 bps). 
 - **Yellow**: ≥ half the threshold. Elevated thinness, building toward alert territory.
 - **Dim**: normal depth.

### Flow Clus

The single largest session aggressive taker-flow price bucket, summarized in one field:

```
0.42% ↑B $1.20M
```

- **0.42%**: the bucket's distance from the current MARK $
- **↑**: the cluster is above the current MARK $
- **B**: buy-notional dominated (B = buy, S = sell)
- **$1.20M**: total notional in this price bucket

**Color conventions**:

- **Red**: buy cluster above MARK (`↑B`). Aggressive buyers concentrated at a price above current. Can act as a retest target or resistance.
- **Green**: sell cluster below MARK (`↓S`). Aggressive sellers concentrated below current price. Can act as support or a reversal zone.
- **Dim**: other combinations (buy cluster below MARK, or sell cluster above MARK) — directionally mixed.

Flow clusters are not stop-loss clusters. They show where actual aggressive trading happened, which can create magnet effects (price retesting a high-volume node) or reversal zones (exhaustion near a prior high-volume sell cluster). Live buckets are anchored to the session VWAP, falling back to the session-open price before enough trade data exists, so an older high-volume zone does not disappear just because the current MARK drifts.

### β/ρ BTC

Two values: BTC beta and BTC return correlation over recent history.

- **Beta**: how much this asset moves per unit of BTC move (e.g., 1.4 means it moves 1.4% when BTC moves 1%)
- **ρ (rho)**: correlation coefficient (-1 to +1) of 1-minute returns
- Format: `0.90/0.18` means beta `0.90`, correlation `0.18`. The BTC row itself shows `base`; rows without enough history show `-`.

**Color**:

- **Red**: high correlation (≥ 0.6). The asset is moving largely with BTC. A squeeze in this asset may be partially explained by BTC.
- **Green**: low correlation (≤ 0.2). The asset is moving independently. A squeeze here is idiosyncratic — and often more violent.
- **Yellow**: moderate correlation (> 0.2 and < 0.6). The asset is partly moving with BTC, so treat idiosyncratic squeeze signals with more caution.

A high-beta, low-correlation asset is particularly interesting: it amplifies BTC moves when correlated but can also move violently on its own crowding dynamics. When you see a squeeze setup forming on a low-correlation asset while BTC is flat, that is a purer signal.

### Drift C/T/B

Data age for three streams: Context / Trades / Book

- **C**: time since last MARK/OI context update
- **T**: time since last trade
- **B**: time since last book update

**Colors**:

- **Red**: > 5 seconds. Data may be stale.
- **Yellow**: > 2 seconds. Lagging.
- **Dim**: fresh data.

A stale trade feed (`T` in red) means the CVD, Taker5, and AvgTrd values are not reflecting the current tape. During a cascade, the trade feed should be actively updating. If `T` goes red while other feeds are fresh, be cautious about acting on CVD or taker% values.

---

## Alerts Panel (Bottom-Left)

Displays at least 12 recent alerts, and more on taller terminals. Each line:

```
[HH:MM:SS] SYMBOL ALERT_KIND Bias: ... | Why: ... | Evidence: ...
```

Alerts are deduplicated: most symbol/kind pairs will not re-fire within a
5-minute window. Funding and flow-cluster alerts use longer dedupe windows
because slow funding plateaus and visible cluster nodes can persist for a long
time.

The details are grouped this way so the alert is useful under time pressure:

**`Bias`**: the margin action the signal points toward. Composite alerts use
directional language such as `open SHORT / close LONG` or `open LONG / close
SHORT`. Simple alerts often say `weak alone` or `context` because a single
metric should not be treated as a full entry signal.

**Strength in parentheses**: how actionable the alert is by itself. `strong`
means multiple conditions are aligned. `moderate` means the setup is plausible
but needs confirmation. `weak alone` and `context` mean the alert is supporting
evidence only.

**`Why`**: the plain-English trading thesis: which side is crowded, whether
positions are opening or closing, whether the book is thin, or whether a move is
late-stage exhaustion.

**`Evidence`**: the specific metrics that caused the alert. These are shown
with labels and semicolon separators so you can quickly compare the alert to the
main table: funding, OI change, taker-buy percentage, CVD, basis, impact, book
imbalance, liquidation volume, or flow-cluster size.

For margin sniping, the important sequence is: first identify the side at risk
(`Bias`), then decide whether the signal is actionable (`Strength`), then check
the listed `Evidence` against the main table before entering or closing a
position.

### Simple Alerts

These fire when a single threshold is breached.

**FUNDING**: yellow

Fires when the absolute funding rate reaches 0.00125%/hr. Either positive or
negative. This is the lowest-bar alert — it signals that positioning has moved
to the current hot-funding plateau. It is necessary but not sufficient for a
squeeze setup.

The details state whether positive funding is a short watch / long-exit clue, or
negative funding is a long watch / short-exit clue. It is MARKed `weak alone`
because funding only tells you who is paying; it does not prove that leverage is
still opening or that the book is ready to move.

**OI_1H**: magenta

Fires when 1-hour open interest has changed by more than 0.75%, or when the
1-hour OI notional change exceeds 1.5% of the asset's 24-hour volume. The
volume-relative path matters for XRP, SOL, and HYPE because a smaller percentage
OI move can still be large versus normal turnover. Combined with directional
taker flow, this tells you who opened positions. Combined with thin book, it
tells you the unwind could be disorderly.

The details distinguish `leverage opening` from `deleveraging / take-profit
clue`. Rising OI adds fuel to a squeeze setup; falling OI suggests positions are
already closing and the move may be more mature.

**THIN_BOOK**: bold red

Fires when impact excess exceeds the symbol's threshold. A thin book by itself is not a setup — thinness is structural in some MARKets. But thin book combined with elevated funding, rising OI, and one-sided flow means any forced unwind will have minimal cushion.

The details call this a `cascade amplifier`. It does not choose long or short by
itself; it tells you that whichever crowded side is forced out may move price
farther because liquidity is thin.

**FLOW_CLUSTER**: cyan

Fires when the largest taker-flow price bucket exceeds the stricter alert-only
volume-scaled notional threshold, has enough trades, and is at least 70%
one-sided. This is the taker-flow analog to a liquidation cluster — a price zone
where a large amount of aggressive trading has concentrated. The bottom-right
panel can still show smaller clusters for context; the alert is reserved for
material, directional clusters.

The details label the cluster as a `long crowding zone` or `short crowding
zone`, then show the cluster price, trade count, notional, and one-sided
dominance. Treat this as context for where crowded entries may sit, not as a
standalone entry.

### Composite Alerts

These fire when multiple conditions align simultaneously. They are the primary actionable signals.

**LONG_SQUEEZE**: bold red

All of the following must be true:
- Funding is positive at or above the squeeze threshold
- OI is rising (new longs are still opening or net buying is occurring)
- The tape is crowded with buyers (taker% ≥ ~60%)
- The book is thin or ask-heavy (Impact or imbalance condition)

This alert says: longs are crowded, more longs keep opening, the book cannot absorb a forced unwind, and taker flow confirms the crowding. The setup is loaded for a downside cascade if price reverses and the weakest longs start getting liquidated.

The details use `Bias: open SHORT / close LONG (strong)` because this is the
cleanest short-side sniping setup: long crowding, rising leverage, buyer-heavy
tape, and a thin or ask-heavy book all point to long exits becoming forced sell
pressure.

**SHORT_SQUEEZE**: bold green

All of the following must be true:
- Funding is negative at or below the squeeze threshold
- OI is rising
- Taker flow is sell-dominated (sellers are crowded)
- Perp is trading below spot (negative basis)

This alert says: shorts are crowded, they have pushed the perp below spot, more shorts keep opening, and the setup is fragile for a violent short-covering rally if price moves up even modestly.

The details use `Bias: open LONG / close SHORT (strong)` because shorts are
paying, short-side leverage is building, the tape is sell-dominated, and
negative basis adds mean-reversion pressure back toward spot.

**CAPITULATION**: bold green

All of the following must be true:
- Aggressive sell CVD has been sharp and negative over 5 minutes
- Taker% is low (sellers still crowded)
- Perp is trading below spot (basis negative)
- Book impact is elevated (the book is thin)

This alert identifies forced selling into a thin book. The selling is not organized — it looks like liquidation-driven unloading. A CAPITULATION alert can MARK the exhaustion point of a downside move, where all the weak longs have been forced out and the MARKet is ready to mean-revert upward. Going long into capitulation is higher risk than going long before a cascade (because the move has already happened), but the reversal can also be sharp.

The details use `Bias: close SHORT / consider LONG (strong but late)`. The
priority is usually exit management if you were already short; a fresh long
needs extra confirmation because the alert fires after forced selling is already
underway.

**GRINDING_TRAP**: bold yellow

All of the following must be true:
- Price is rising at least 1.5 standard deviations (in σ15m terms) over 15 minutes
- CVD is flat or negative (buying is not actually driving the price up)
- Funding is rising
- OI is expanding

This is a structural warning rather than an immediate trigger. Price is grinding up, but there is no real aggressive buying behind it — CVD would be positive if buyers were driving it. Instead, the price is rising because sellers are pulling their asks (a thin book rising) while funding and OI build. This is the setup most likely to reverse sharply when the last buyer exhausts. The GRINDING_TRAP alert says "this move is fragile — funding is rising, longs are building, but no one is actually chasing it aggressively."

The details use `Bias: avoid LONG / probe SHORT (moderate)`. It is weaker than
LONG_SQUEEZE because the alert is about fragility, not confirmed unwind. Use it
to stop chasing a long and watch for rollover confirmation.

---

## Liquidation Clusters Panel (Bottom-Right) — "Liq Clusters (1h)"

This panel shows every liquidation cluster per symbol that passes the configured
1-hour cluster filters. Liquidation events come from Bybit `allLiquidation` and
are mapped to the Hyperliquid watchlist by coin. Each line:

```
SYMBOL ↑/↓ L/S @ price ##.##% away x# $####
```

**Symbol**: bold white label for the asset

**Arrow (↑ or ↓)**:
- `↑` — the cluster is *above* the current MARK $
- `↓` — the cluster is *below* the current MARK $

**L or S**:
- `L` (Long liquidations) — liquidated longs dominate this price bucket; this is forced selling
- `S` (Short liquidations) — liquidated shorts dominate this price bucket; this is forced buying

**Combined color of the arrow + letter**:
- **Red** (`↓L`) — long liquidations dominate; forced sellers are hitting the book.
- **Green** (`↑S`) — short liquidations dominate; forced buyers are lifting the book.

**`##.##% away`**: how far the cluster price is from the current MARK, as a percentage. Shown in dim style. This tells you how much price would need to move to reach that zone of prior aggressive activity.

**`x#`**: the number of liquidation events aggregated into this bucket. More events means the level has been hit repeatedly. A cluster with x20 events is more meaningful than one with x2.

**`$####`**: the total notional (in USD, using short format: k, M, B) in this price bucket. The size of the cluster reflects how much forced closing happened there.

Liquidation bucket width is controlled by `LIQ_CLUSTER_BUCKET_PCT`; relevance is
controlled by the 1-hour window and `LIQ_CLUSTER_MIN_COUNT`. The dashboard does
not apply a separate top-N display cap.

**How to use liquidation clusters**:

Clusters are not Hyperliquid-native liquidation maps. They show where Bybit
forced closes happened, which is still useful cross-venue pressure:

- **Cascade confirmation**: repeated long liquidations below MARK confirm downside forced selling.
- **Exhaustion MARKers**: large long-liquidation clusters after a selloff can MARK where weak longs have already been flushed.
- **Squeeze confirmation**: repeated short liquidations above MARK confirm upside forced buying.

If `LIQUIDATION_FEED_ENABLED` is turned off, this panel falls back to "Flow
Clusters (session)", a VWAP-anchored view of aggressive taker-flow buckets from
the current run.

---

## Example Scenarios

---

### Example 1 — Short Side: Riding a Long Squeeze

**Setup goal**: Enter short before a leveraged long cascade unwinds.

---

**Step 1: Initial trigger — LONG_SQUEEZE alert fires**

The Alerts panel shows:

```
[14:32:11] SOL-USDC LONG_SQUEEZE Bias: open SHORT / close LONG (strong) | Why: crowded longs are building into a thin or ask-heavy book | Evidence: funding +0.0120%; funding 1h +0.0040pp; OI 1h +2.1%; taker buy 67%; impact thin 4.2bp
```

This composite alert tells you the candidate action first: look for a short
entry, or close/reduce an existing long. The evidence says funding is elevated
(longs are paying), OI has been rising (new longs are still opening), the taker
tape is crowded with buyers, and the book is thin enough for a forced unwind to
travel. This is your first reason to look at SOL closely.

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

**β/ρ BTC**: `0.90/0.18` in green — low BTC correlation. This setup is largely idiosyncratic to SOL, not just BTC dragging it around.

All of these are consistent and reinforcing. This is a high-quality setup.

---

**Step 3: Check the Liq Clusters panel for liquidation structure**

```
SOL ↓L @ 145.10 1.78% away x12 $420k
SOL ↑S @ 148.32 0.41% away x4 $180k
```

The dominant cluster is long liquidations below current MARK. Longs have already
been forced out at that lower level, and the cluster is close enough that a
renewed drop could reconnect with the same forced-selling zone.

This tells you the long side is fragile below the current level. If price drops
even modestly and OI remains elevated, the next wave of longs can be pushed into
the same forced-selling path.

---

**Step 4: Look for what would *not* support this trade**

Before entering, check what would undermine the thesis:

- **If σ15m were spiking red** (> 1.0%) — a cascade may have already started and you would be entering mid-move with less edge
- **If BTC correlation were high (ρ > 0.6 in red)**: the move might be explained by BTC lifting, not idiosyncratic crowding. Check if BTC funding is also elevated.
- **If OI were falling instead of rising**: positions are closing, not building. The trigger may have already fired.
- **If the book showed a large bid wall (B3.0x)**: a large buyer is defending a level. This can temporarily prevent a cascade even when other signals line up.
- **If the CVD 1m were flipping green while 5m/15m stay red**: short-horizon exhaustion is appearing. This can either be the first signal of a roll, or just noise. Wait to see if the 5m follows.

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

- **CAPITULATION alert fires**: the sell cascade has reached the exhaustion stage. The forced selling is late-stage, not early. If you entered early and rode this, the alert is your exit signal.
- **CVD 1m and 5m both flip green and are deepening**: selling is accelerating but OI is also falling fast, meaning liq cascade is advanced.
- **SHORT_SQUEEZE alert fires for the same symbol**: conditions have flipped. The MARKet has moved so far down that shorts (yours included) are now at risk.
- **Basis turns sharply positive**: perp is now trading above spot, meaning buyers have returned and the unwind may be over.
- **Book imbalance flips from negative (ask-heavy) to positive (bid-heavy)**: buyers are stepping back in at the book level.

These indicators are often concurrent: a CAPITULATION alert usually fires alongside a CVD flip, a rising book imbalance, and a basis reversal. When you see two or more of them at once, exit quickly — the move is done.

---

### Example 2 — Long Side: Riding a Short Squeeze

**Setup goal**: Enter long before a crowded short position unwinds in a covering rally.

---

**Step 1: Initial trigger — SHORT_SQUEEZE alert fires**

The Alerts panel shows:

```
[09:14:44] ETH-USDC SHORT_SQUEEZE Bias: open LONG / close SHORT (strong) | Why: crowded shorts may cover into spot/bid support | Evidence: funding -0.0090%; OI 1h +1.4%; taker buy 28%; basis -0.310%; bid-heavy book
```

The alert points to a long entry or a short exit before showing the evidence.
Funding is deeply negative (shorts are paying longs), OI is rising (new shorts
are still opening), the tape is sell-dominated (28% taker buy = 72% aggressive
selling), and the perp is trading 0.31% below spot. This is the short-squeeze
fuel stack: shorts are crowded, they have driven the perp below spot, and they
are still pressing.

---

**Step 2: Scan the main table row**

**Fund/FΔ1h**: `−0.009% / ↓−0.003%` in bold green — funding is already negative and getting *more* negative. Shorts are being added continuously.

**Basis%**: `−0.31` — the perp is 0.31% below Hyperliquid spot. This is meaningful: arbitrageurs and spot holders have an incentive to sell spot and buy perp to capture this basis, which mechanically bids the perp back up toward spot. The more negative basis becomes, the stronger that mean-reversion pull.

**OI Δ15m%**: `+2.3%` — open interest is still rising rapidly. New short positions are opening.

**CVD 1/5/15**: Green across all timeframes — `−$1.8M / −$7.2M / −$19M`. Aggressive sellers have dominated every timeframe. The crowd has been consistently selling.

**Taker5**: `26%` in bold green — aggressive buying is almost absent. Nearly all aggressive participation has been selling.

**Book**: `3.8bp / +22% / B1.9x` — the book is bid-heavy (more resting bids than asks, +22% imbalance). Despite the aggressive selling, there are more limit-buy orders sitting than limit-sell orders. This is a divergence: the active traders are selling aggressively while the passive book is supporting bids. This is often a sign that the aggressive sellers are running out of willing passive counterparties.

**Impact**: Yellow — elevated thinness, not yet at alert threshold but notable.

**β/ρ BTC**: `1.20/0.14` in green — low BTC correlation. ETH is moving on its own dynamics, not BTC drag.

---

**Step 3: Check Liq Clusters for structural context**

```
ETH ↑S @ 3,298.40 0.71% away x19 $1.1M
ETH ↓L @ 3,242.10 0.88% away x6 $390k
```

The dominant cluster is short liquidations above current MARK. $1.1M in forced
buying happened at that level. This tells you that shorts have already been
stressed above the MARKet, and a move back into that zone can restart forced
covering.

The smaller long-liquidation cluster below is less relevant for the long setup.

The key insight: if price moves upward from here, the crowd of shorts who entered at 3,242 will see their positions approach breakeven. If they are leveraged, their margin cushion shrinks fast. At some point, covering orders start going in.

---

**Step 4: Look for what would *not* support this trade**

- **If basis were positive**: the perp is not below spot, so there is no mean-reversion mechanical pressure. The short-squeeze setup requires perp below spot.
- **If OI were falling**: shorts are already covering, the move may have started without you.
- **If the book were ask-heavy despite funding being negative**: passive sellers are willing to provide supply, which dampens the squeeze. The book in this example is bid-heavy, which is supportive.
- **If BTC were also showing elevated negative funding**: this might be a BTC-correlated macro sell-off, not an idiosyncratic ETH short squeeze. Check β/ρ BTC.
- **If σ15m were already > 1.0% (red)**: volatility is already spiking. The covering rally may have started and you are entering late into an already-moving MARKet.

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

- **LONG_SQUEEZE alert fires for ETH**: the situation has completely inverted. The covering rally overshot and now longs are crowded. This is a hard exit signal.
- **CVD 1m flips back to green after spiking red**: the covering rally stalled. Aggressive selling is returning.
- **Basis turns sharply positive** (perp now above spot) — the mean-reversion that fueled the squeeze is now working against you in the other direction.
- **OI is rising again while CVD is red**: new shorts are opening at the higher price. The squeeze may be over and the MARKet is re-pressing short.
- **GRINDING_TRAP alert fires**: if price has risen but CVD is now flat or negative, the move may be a weak grind without real covering demand. The fragility alert means the up-move could reverse.

As with the short example, multiple indicators often appear together at turning points. Basis turning positive, CVD flipping green, and a LONG_SQUEEZE alert arriving in quick succession are collectively a strong signal to exit.

---

## Quick Reference: Signal Hierarchy for Margin Sniping

Not all signals are equal. Here is a rough priority order for building a thesis:

1. **Composite alert fires** (LONG_SQUEEZE, SHORT_SQUEEZE, CAPITULATION, GRINDING_TRAP) — necessary condition for a high-quality setup
2. **CVD stack**: confirms which side is crowded and whether exhaustion is appearing
3. **Funding level and delta**: confirms crowding and whether it is building or fading
4. **Basis**: confirms the perp-vs-spot dislocation that feeds a squeeze
5. **OI Δ15m%**: confirms whether new leverage is still entering
6. **Impact / Book**: confirms the structural thinness that amplifies the cascade
7. **Liq Clusters**: confirms where forced closes are stacking and whether the cascade is active or exhausted
8. **OI/Vol**: provides context on how stale the leverage is (amplifier, not trigger)
9. **β/ρ BTC**: distinguishes idiosyncratic setups from BTC-driven moves

A setup with only one or two of these signals is noise. A setup where five or six of them align is worth your full attention.

---

## Operational Notes

**Wait for history to build.** OI deltas, funding velocity, realized vol, and BTC beta need runtime history before they are meaningful. The columns will show dim or missing values in the first few minutes after launch. Wait at least 15–30 minutes before relying on σ15m, CVD stacks, or β/ρ.

**Impact thresholds are symbol-aware.** Retained Hyperliquid exports showed that
BTC, DOGE, and XRP need different impact baselines. BTC and XRP are overridden
to 2 bps, while DOGE is overridden to 2.5 bps. Treat a THIN_BOOK alert as a
symbol-relative thinness event, not a raw cross-asset comparison.

**Stale drift is an early warning.** If the Drift C/T/B column shows a stale trade feed (T in red) while other feeds are current, do not act on CVD or taker% values — they are not reflecting the current tape. During a cascade, the trade feed should be the most active stream.

**Tuning thresholds.** The defaults in `config.py` are starting points. After watching the dashboard for a session across different MARKet conditions, you will notice which assets trigger alerts too frequently (reduce thresholds) and which seem quiet even when visually there is crowding (increase sensitivity). Use the export script to review historical alert distributions and metric ranges before tightening.
