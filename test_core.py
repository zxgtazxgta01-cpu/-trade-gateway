import unittest

from core import (
    Checklist, Instrument, MockBroker, TradePlan,
    gate, position_size, risk_reward, submit,
)

INST = Instrument(value_per_unit=100.0)  # example contract spec


def ticked(*names, all_done=True):
    return Checklist({n: all_done for n in names})


class RiskRewardTests(unittest.TestCase):
    def test_buy_rr(self):
        plan = TradePlan("buy", entry=100, sl=95, tp=110)
        self.assertAlmostEqual(risk_reward(plan), 2.0)

    def test_sell_rr(self):
        plan = TradePlan("sell", entry=100, sl=104, tp=96)
        self.assertAlmostEqual(risk_reward(plan), 1.0)

    def test_wrong_side_sl_rejected(self):
        plan = TradePlan("buy", entry=100, sl=105, tp=110)
        self.assertTrue(plan.validate())


class PositionSizeTests(unittest.TestCase):
    def test_lots_rounded_down(self):
        plan = TradePlan("buy", 100, 99, 102)
        # risk money = 1000 * 1% = 10; loss/lot = 1 * 100 = 100 -> 0.10 lot
        self.assertAlmostEqual(position_size(1000, 1, plan, INST), 0.10)

    def test_never_rounds_up(self):
        plan = TradePlan("buy", 100, 99.7, 101)
        # 10 / (0.3*100) = 0.3333 -> 0.33
        self.assertAlmostEqual(position_size(1000, 1, plan, INST), 0.33)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.plan = TradePlan("buy", 100, 99, 102)  # RR 2

    def test_blocks_when_checklist_incomplete(self):
        cl = Checklist({"trend ok": True, "news checked": False})
        r = gate(self.plan, cl, 1000, 1, INST)
        self.assertFalse(r.allowed)
        self.assertIn("checklist not ticked: news checked", r.reasons)

    def test_blocks_low_rr(self):
        plan = TradePlan("buy", 100, 99, 100.5)
        r = gate(plan, ticked("a"), 1000, 1, INST, min_rr=1.5)
        self.assertFalse(r.allowed)

    def test_blocks_excess_risk(self):
        r = gate(self.plan, ticked("a"), 1000, 5, INST)
        self.assertFalse(r.allowed)

    def test_allows_valid_order(self):
        r = gate(self.plan, ticked("a", "b"), 1000, 1, INST)
        self.assertTrue(r.allowed)
        self.assertAlmostEqual(r.rr, 2.0)

    def test_submit_only_calls_broker_when_allowed(self):
        broker = MockBroker()
        blocked, oid = submit(broker, self.plan, ticked("a", all_done=False), 1000, 1, INST)
        self.assertIsNone(oid)
        self.assertEqual(broker.orders, [])
        ok, oid = submit(broker, self.plan, ticked("a"), 1000, 1, INST)
        self.assertEqual(oid, "MOCK-1")
        self.assertEqual(len(broker.orders), 1)


if __name__ == "__main__":
    unittest.main()
