from __future__ import annotations

import config
from signals import evaluate_signal_set
from state import SymbolState


def test_evaluate_signal_set_builds_long_squeeze() -> None:
    now_ms = 1_800_000
    state = SymbolState()
    state.mark = 100.0
    state.mid = 100.0
    state.oracle = 99.9
    state.day_ntl_vlm = 100_000_000.0
    state.record_mark(now_ms - 1_000)
    state.record_funding(now_ms - 1_000, 0.00006)
    state.record_oi(now_ms - 3_700_000, 100.0)
    state.record_oi(now_ms - 1_000, 102.0)
    state.add_trade(now_ms - 1_000, is_buyer_maker=False, qty=50.0, price=100.0)
    state.record_book(
        now_ms - 1_000,
        bids=[{"px": "99.9", "sz": "10"}],
        asks=[{"px": "100.1", "sz": "100"}],
    )

    result = evaluate_signal_set({config.WATCHLIST[0]: state}, now_ms=now_ms)

    assert len(result) == 1
    assert result[0].action == "OPEN SHORT / CLOSE LONG"
    assert result[0].title == "Crowded Long Squeeze"
    assert len(result[0].confirmations) >= 3


def test_evaluate_signal_set_skips_empty_state() -> None:
    result = evaluate_signal_set({config.WATCHLIST[0]: SymbolState()}, now_ms=1_000)

    assert result == []
