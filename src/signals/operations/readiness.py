"""Observation-only H-A…H-G readiness evaluation."""

from __future__ import annotations

from signals.operations.contracts import AutonomousReadiness, GateStatus, ReadinessEvidence
from signals.policy.contracts import AutonomyMode


def evaluate_readiness(evidence: ReadinessEvidence) -> AutonomousReadiness:
    gates = (
        evidence.h_a_runtime,
        evidence.h_b_state,
        evidence.h_c_policy,
        evidence.h_d_shadow,
        evidence.h_e_capped,
        evidence.h_f_closed_loop,
        evidence.h_g_scale,
    )
    blockers = tuple(
        sorted(
            {
                code
                for gate in gates
                if gate.status is not GateStatus.READY
                for code in gate.reason_codes
            }
        )
    )
    refs = tuple(sorted({ref for gate in gates for ref in gate.evidence_refs}))
    if all(gate.status is GateStatus.READY for gate in gates):
        mode = AutonomyMode.ADAPTIVE_SCALE
    elif all(
        gate.status is GateStatus.READY
        for gate in (evidence.h_a_runtime, evidence.h_b_state, evidence.h_c_policy, evidence.h_e_capped)
    ):
        mode = AutonomyMode.AUTONOMOUS_CAPPED
    elif all(
        gate.status is GateStatus.READY
        for gate in (evidence.h_a_runtime, evidence.h_b_state, evidence.h_c_policy)
    ):
        mode = AutonomyMode.ASSISTED
    else:
        mode = AutonomyMode.SHADOW
    return AutonomousReadiness(
        evaluated_at=evidence.evaluated_at,
        h_a_runtime=evidence.h_a_runtime,
        h_b_state=evidence.h_b_state,
        h_c_policy=evidence.h_c_policy,
        h_d_shadow=evidence.h_d_shadow,
        h_e_capped=evidence.h_e_capped,
        h_f_closed_loop=evidence.h_f_closed_loop,
        h_g_scale=evidence.h_g_scale,
        highest_safe_mode=mode,
        blockers=blockers,
        evidence_refs=refs,
    )
