"""Trade Gateway core: RR calculation, risk-based position sizing, checklist gate.

Pure Python, no dependencies, no broker code. The broker side plugs in
through the BrokerAdapter interface (MockBroker now, MT5 later).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TradePlan:
    side: str   # "buy" or "sell"
    entry: float
    sl: float
    tp: float

    def validate(self) -> list[str]:
        """Return a list of problems; empty list means the plan is consistent."""
        errors = []
        if self.side not in ("buy", "sell"):
            errors.append("side must be 'buy' or 'sell'")
            return errors
        if self.side == "buy":
            if not self.sl < self.entry:
                errors.append("buy: SL must be below entry")
            if not self.tp > self.entry:
                errors.append("buy: TP must be above entry")
        else:
            if not self.sl > self.entry:
                errors.append("sell: SL must be above entry")
            if not self.tp < self.entry:
                errors.append("sell: TP must be below entry")
        return errors

    @property
    def risk_distance(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def reward_distance(self) -> float:
        return abs(self.tp - self.entry)


def risk_reward(plan: TradePlan) -> float:
    """Reward divided by risk (e.g. 2.0 means 1:2)."""
    if plan.risk_distance == 0:
        raise ValueError("entry and SL are equal")
    return plan.reward_distance / plan.risk_distance


@dataclass(frozen=True)
class Instrument:
    """Contract spec. value_per_unit = money gained/lost per 1.0 price move per 1 lot."""
    value_per_unit: float
    lot_step: float = 0.01
    min_lot: float = 0.01
    max_lot: float = 100.0


def position_size(balance: float, risk_pct: float, plan: TradePlan, inst: Instrument) -> float:
    """Lots so that hitting SL loses about risk_pct % of balance (rounded DOWN to lot step)."""
    if balance <= 0 or risk_pct <= 0:
        raise ValueError("balance and risk_pct must be positive")
    risk_money = balance * risk_pct / 100
    loss_per_lot = plan.risk_distance * inst.value_per_unit
    raw = risk_money / loss_per_lot
    steps = math.floor(raw / inst.lot_step + 1e-9)
    lots = round(steps * inst.lot_step, 8)
    return min(max(lots, 0.0), inst.max_lot)


@dataclass
class Checklist:
    """Every item must be ticked before an order is allowed."""
    items: dict[str, bool] = field(default_factory=dict)

    def tick(self, name: str, value: bool = True) -> None:
        if name not in self.items:
            raise KeyError(f"unknown checklist item: {name}")
        self.items[name] = value

    def missing(self) -> list[str]:
        return [name for name, done in self.items.items() if not done]


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reasons: list[str]
    rr: float | None = None
    lots: float | None = None


def gate(
    plan: TradePlan,
    checklist: Checklist,
    balance: float,
    risk_pct: float,
    inst: Instrument,
    min_rr: float = 1.0,
    max_risk_pct: float = 2.0,
) -> GateResult:
    """Decide whether an order may be opened. Collects ALL reasons for blocking."""
    reasons = plan.validate()
    if reasons:
        return GateResult(False, reasons)

    rr = risk_reward(plan)
    if rr < min_rr:
        reasons.append(f"RR {rr:.2f} is below minimum {min_rr:.2f}")
    if risk_pct > max_risk_pct:
        reasons.append(f"risk {risk_pct}% exceeds cap {max_risk_pct}%")
    for name in checklist.missing():
        reasons.append(f"checklist not ticked: {name}")

    lots = position_size(balance, risk_pct, plan, inst)
    if lots < inst.min_lot:
        reasons.append("lot size below broker minimum for this risk")

    return GateResult(not reasons, reasons, rr=rr, lots=lots)


class BrokerAdapter(Protocol):
    def place_order(self, plan: TradePlan, lots: float) -> str:
        """Send the order and return an order id."""


class MockBroker:
    """Paper-trading stand-in. Replace with an MT5 adapter later."""

    def __init__(self) -> None:
        self.orders: list[tuple[str, TradePlan, float]] = []

    def place_order(self, plan: TradePlan, lots: float) -> str:
        order_id = f"MOCK-{len(self.orders) + 1}"
        self.orders.append((order_id, plan, lots))
        return order_id


def submit(
    broker: BrokerAdapter,
    plan: TradePlan,
    checklist: Checklist,
    balance: float,
    risk_pct: float,
    inst: Instrument,
    **gate_kwargs,
) -> tuple[GateResult, str | None]:
    """Run the gate; only call the broker if it passes."""
    result = gate(plan, checklist, balance, risk_pct, inst, **gate_kwargs)
    if not result.allowed:
        return result, None
    return result, broker.place_order(plan, result.lots)
