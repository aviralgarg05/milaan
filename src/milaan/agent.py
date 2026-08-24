"""The reconciliation agent: a policy loop over strategies, with an auditable trace.

Track 04 asks for an *agent* that closes a finance-ops loop. An earlier version of
MILAAN was not one, and calling it one would have been a relabelling — the control
flow was `filter pool -> try interval -> else try blind -> emit verdict`, a
straight line with no loop, no state and no decision. An auditor said so and was
right (INCIDENTS.md #23).

What makes this one different is not vocabulary. It is that **a fixed candidate
window was the wrong design**, and fixing it requires exactly the thing an agent
provides: observing an outcome, deciding what to try next, and trying again.

The window is the whole problem. A bank credit is composed of transactions
captured in some interval before it, and the engine does not know that interval.
Pick it too wide and the pool fills with a neighbouring settlement's rows, so
several subsets tie and the honest verdict is AMBIGUOUS. Pick it too narrow and a
genuine member is excluded, so nothing sums and the honest verdict is NO_COVER.
Those two failures point in **opposite directions**, which is what makes a fixed
window indefensible and a feedback loop the natural answer:

    NO_COVER   -> the pool is too small. Widen it.
    AMBIGUOUS  -> the pool is too big.  Narrow it.
    UNIQUE     -> stop.

That is a genuine control policy over a genuine state variable, and it is
deterministic — no model is consulted, because the signal (which way the last
attempt failed) is unambiguous and a language model could only add noise to a
decision that arithmetic already answers. This is the "where you chose not to use
one" boundary drawn at the level of the agent's own reasoning, not just its
tools.

**Bounded by construction.** Every episode terminates: the window is drawn from a
fixed ascending ladder, each rung is tried at most once, and the loop cannot run
longer than the ladder. There is no unbounded retry, no widening past the point
where a settlement could plausibly reach, and a per-credit action budget that
turns exhaustion into an explicit `ESCALATE` rather than a hang.

**Auditable.** Every episode returns the full sequence of (observation, action,
outcome) it went through. `milaan run --trace` prints it. An agent whose decisions
cannot be replayed is not something a finance team should run near money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .hints.grounding import Candidate, resolve
from .narration.grammar import NarrationFields
from .solver.interval import find_intervals
from .solver.subsetsum import Budget, Outcome

__all__ = ["Action", "Observation", "Step", "Episode", "ReconciliationAgent", "WINDOW_LADDER"]

# Ascending candidate windows in days. Starts tight because a settlement's
# members are captured close together, and stops at 6 because Razorpay settles on
# T+2 working days — a member more than a week from the value date is not part of
# this settlement, it is evidence of a different problem.
WINDOW_LADDER: tuple[int, ...] = (1, 2, 3, 4, 6)


class Action(str, Enum):
    TRY_INTERVAL = "TRY_INTERVAL"
    """Search contiguous runs in capture order at the current window."""

    WIDEN = "WIDEN"
    """Last attempt found no cover: a member is probably outside the window."""

    NARROW = "NARROW"
    """Last attempt found several: the pool probably spans two settlements."""

    TRY_BLIND = "TRY_BLIND"
    """Contiguity failed at every window. Fall back to unordered subset-sum."""

    ACCEPT = "ACCEPT"
    """A unique exact cover. Terminal."""

    ESCALATE = "ESCALATE"
    """No window yields a decision. Terminal, and a refusal — not a guess."""


@dataclass(frozen=True, slots=True)
class Observation:
    """What the agent can see before choosing. Never includes the answer key."""

    window_days: int
    pool_size: int
    last_outcome: Outcome | None
    attempts: int
    narration_opaque: bool
    rungs_left: int


@dataclass(frozen=True, slots=True)
class Step:
    observation: Observation
    action: Action
    outcome: Outcome | None = None
    note: str = ""


@dataclass
class Episode:
    credit_id: str
    steps: list[Step] = field(default_factory=list)
    outcome: Outcome = Outcome.NONE
    cover: tuple[str, ...] = ()
    second_cover: tuple[str, ...] = ()
    final_window: int = 0
    layer: str = "interval"

    @property
    def actions(self) -> str:
        return " → ".join(s.action.value for s in self.steps)


class ReconciliationAgent:
    """Chooses a candidate window per credit by reacting to how the last try failed."""

    def __init__(self, *, budget: Budget | None = None,
                 ladder: tuple[int, ...] = WINDOW_LADDER,
                 max_actions: int = 12) -> None:
        self.budget = budget
        self.ladder = ladder
        self.max_actions = max_actions

    # -- the policy. Deterministic, and the only place strategy is decided. ---
    def decide(self, obs: Observation) -> Action:
        # No outcome to react to — either the first attempt, or the window was
        # just changed and nothing has been tried at the new one yet.
        if obs.attempts == 0 or obs.last_outcome is None:
            return Action.TRY_INTERVAL
        if obs.last_outcome is Outcome.UNIQUE:
            return Action.ACCEPT
        if obs.last_outcome is Outcome.NONE:
            # Nothing summed. Either a member is outside the window (widen), or
            # contiguity is the wrong assumption for this credit (go unordered).
            return Action.WIDEN if obs.rungs_left > 0 else Action.TRY_BLIND
        if obs.last_outcome is Outcome.AMBIGUOUS:
            # Several ties. A tighter window may exclude the neighbouring
            # settlement that is causing them; if we are already at the tightest,
            # the ambiguity is real and must be refused rather than broken.
            return Action.NARROW if obs.window_days > self.ladder[0] else Action.ESCALATE
        return Action.ESCALATE

    def run(self, *, credit_id: str, target_paise: int, value_date: date,
            rows: list[tuple[str, int, str, date]], fields: NarrationFields) -> Episode:
        """Resolve one credit. `rows` is (entity_id, net_paise, captured_at, captured_on)."""
        ep = Episode(credit_id=credit_id)
        rung = 0
        last: Outcome | None = None

        while len(ep.steps) < self.max_actions:
            window = self.ladder[rung]
            pool = [
                Candidate(eid, net, abs((cap_on - value_date).days), reference=cap_at)
                for eid, net, cap_at, cap_on in rows
                if abs((cap_on - value_date).days) <= window
            ]
            obs = Observation(
                window_days=window, pool_size=len(pool), last_outcome=last,
                attempts=len(ep.steps), narration_opaque=fields.is_opaque,
                rungs_left=len(self.ladder) - rung - 1,
            )
            action = self.decide(obs)

            if action is Action.ACCEPT:
                # A unique cover at a NARROW window is not yet an answer. Widening
                # may reveal a second run that also sums exactly, in which case the
                # credit is genuinely ambiguous and the narrow window merely hid
                # the competitor. Accepting here would be *manufacturing*
                # uniqueness by shrinking the pool — the identical move that
                # `hints/grounding.py` forbids a hint from making, and it produced
                # a real wrong join before this check existed (INCIDENTS.md #24).
                #
                # So: find narrow, adjudicate wide. Uniqueness is always decided
                # at the widest window on the ladder.
                widest = self.ladder[-1]
                wide_pool = [
                    Candidate(eid, net, abs((cap_on - value_date).days), reference=cap_at)
                    for eid, net, cap_at, cap_on in rows
                    if abs((cap_on - value_date).days) <= widest
                ]
                wide_ordered = sorted(wide_pool, key=lambda c: (c.reference or "", c.entity_id))
                wide = find_intervals([c.net_paise for c in wide_ordered], target_paise)
                if wide.ambiguous:
                    ep.steps.append(Step(
                        obs, Action.ESCALATE, Outcome.AMBIGUOUS,
                        f"unique at ±{ep.final_window}d but {len(wide.covers)} covers at "
                        f"±{widest}d — the narrow window hid a competitor, refusing"))
                    ep.outcome = Outcome.AMBIGUOUS
                    ep.second_cover = tuple(
                        wide_ordered[i].entity_id for i in wide.covers[1])
                    return ep
                ep.steps.append(Step(obs, action, last,
                                     f"unique at ±{ep.final_window}d and still unique at ±{widest}d"))
                ep.outcome = Outcome.UNIQUE
                return ep

            if action is Action.ESCALATE:
                ep.steps.append(Step(obs, action, last,
                                     "ambiguity survives the tightest window — refusing"))
                ep.outcome = last or Outcome.NONE
                return ep

            if action is Action.WIDEN:
                rung += 1
                ep.steps.append(Step(obs, action, last,
                                     f"no cover at ±{window}d, widening to ±{self.ladder[rung]}d"))
                last = None
                continue

            if action is Action.NARROW:
                rung -= 1
                ep.steps.append(Step(obs, action, last,
                                     f"{'several covers'} at ±{window}d, "
                                     f"narrowing to ±{self.ladder[rung]}d"))
                last = None
                continue

            if action is Action.TRY_BLIND:
                r = resolve(pool, target_paise, budget=self.budget)
                ep.steps.append(Step(obs, action, r.outcome, "unordered subset-sum"))
                ep.outcome, ep.cover, ep.second_cover = r.outcome, r.cover, r.second_cover
                ep.final_window, ep.layer = window, "blind"
                return ep

            # TRY_INTERVAL
            ordered = sorted(pool, key=lambda c: (c.reference or "", c.entity_id))
            iv = find_intervals([c.net_paise for c in ordered], target_paise)
            if iv.unique:
                last = Outcome.UNIQUE
                ep.cover = tuple(ordered[i].entity_id for i in iv.covers[0])
                ep.second_cover = ()
            elif iv.ambiguous:
                last = Outcome.AMBIGUOUS
                ep.cover = tuple(ordered[i].entity_id for i in iv.covers[0])
                ep.second_cover = tuple(ordered[i].entity_id for i in iv.covers[1])
            else:
                last = Outcome.NONE
                ep.cover = ep.second_cover = ()
            ep.final_window, ep.layer = window, "interval"
            ep.steps.append(Step(obs, action, last,
                                 f"±{window}d, pool={len(pool)}, {len(iv.covers)} cover(s)"))

        ep.steps.append(Step(obs, Action.ESCALATE, last, "action budget exhausted"))
        ep.outcome = last or Outcome.NONE
        return ep
