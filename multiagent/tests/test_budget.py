from buyer_agent.budget import WORST_CASE_CALLS, CallBudget


def test_worst_case_constant_is_22():
    assert WORST_CASE_CALLS == 22


def test_take_until_400_then_refuse():
    b = CallBudget(400, clock=lambda: 0.0)
    assert sum(b.try_take(WORST_CASE_CALLS) for _ in range(30)) == 18  # 18 * 22 = 396
    assert b.try_take(4) and not b.try_take(1)


def test_window_slides_after_one_hour():
    now = [0.0]
    b = CallBudget(22, clock=lambda: now[0])
    assert b.try_take(22) and not b.try_take(1)
    now[0] = 3599.0
    assert not b.try_take(1)
    now[0] = 3600.0
    assert b.try_take(22)
