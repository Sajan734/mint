from buyer_agent.budget import WORST_CASE_CALLS, CallBudget


def test_worst_case_constant_is_34():
    assert WORST_CASE_CALLS == 34


def test_take_until_400_then_refuse():
    b = CallBudget(400, clock=lambda: 0.0)
    assert sum(b.try_take(WORST_CASE_CALLS) for _ in range(30)) == 11  # 11 * 34 = 374
    assert b.try_take(26) and not b.try_take(1)


def test_window_slides_after_one_hour():
    now = [0.0]
    b = CallBudget(22, clock=lambda: now[0])
    assert b.try_take(22) and not b.try_take(1)
    now[0] = 3599.0
    assert not b.try_take(1)
    now[0] = 3600.0
    assert b.try_take(22)


def test_reserve_covers_the_largest_allowed_manifest():
    from buyer_agent.budget import WORST_CASE_CALLS
    from buyer_agent.sources import MAX_PAIRS

    assert WORST_CASE_CALLS >= MAX_PAIRS + 8 + 2
