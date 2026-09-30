"""Network turns opt out of the owner guard (issue 110, ADR 0008): they build with
``guard=None``, so an enrolled guard never locks the tau network."""

from __future__ import annotations

from net_helpers import ALICE, BOB, Pair, poll
from tau_core.guard import ENROLLED_MARKER, reset_guards, resolve_guard


def test_network_turns_run_while_a_guard_is_active(pair_factory) -> None:
    pair: Pair = pair_factory(replies=["Nice to meet you."])
    marker = pair.b.config.data_dir / ENROLLED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"v": 1, "enrollment": "E1"}', encoding="utf-8")
    reset_guards()
    try:
        assert resolve_guard(pair.b.config) is not None  # guarded channels would be locked
        pair.a_node.send(BOB, "Hello from Alice's tau.")
        poll(pair.b_node)
        assert len(pair.b.model.calls) == 1  # the turn ran
        assert pair.b_node.turns.agent(ALICE).guard is None
    finally:
        reset_guards()
