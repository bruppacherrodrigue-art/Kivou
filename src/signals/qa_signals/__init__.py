"""QA Signals contracts with no live provider wiring."""

from signals.qa_signals.contracts import QaDecision, QaStatus
from signals.qa_signals.protocol import QaSignals

__all__ = ["QaDecision", "QaSignals", "QaStatus"]
