"""Alertes client — SPEC-014.

Un cycle appelable (`run_alert_cycle`), une passerelle d'envoi remplaçable, et
une politique de cadence qui lit le catalogue de facturation plutôt que d'en
inventer un second.
"""

from signals.alerts.delivery import (
    DeliveryBatch,
    DeliveryStateConflict,
    logical_batch_key,
    retry_delay,
)
from signals.alerts.gateway import (
    AlertDeliveryError,
    AlertDeliveryGateway,
    AlertMessage,
    DeliveryResult,
    SmtpAlertGateway,
    SmtpConfiguration,
    UncertainDelivery,
    message_id,
)
from signals.alerts.job import AlertOutcome, CycleReport, eligible_signals, run_alert_cycle
from signals.alerts.lease import LeaseAcquisition, acquire, release
from signals.alerts.policy import (
    ALERT_POLICY_VERSION,
    MAXIMUM_SIGNALS_PER_EMAIL,
    SENDING_CADENCES,
    is_due,
)

__all__ = [
    "ALERT_POLICY_VERSION",
    "MAXIMUM_SIGNALS_PER_EMAIL",
    "SENDING_CADENCES",
    "AlertDeliveryError",
    "AlertDeliveryGateway",
    "AlertMessage",
    "AlertOutcome",
    "CycleReport",
    "DeliveryBatch",
    "DeliveryResult",
    "DeliveryStateConflict",
    "LeaseAcquisition",
    "SmtpAlertGateway",
    "SmtpConfiguration",
    "UncertainDelivery",
    "acquire",
    "eligible_signals",
    "is_due",
    "logical_batch_key",
    "message_id",
    "release",
    "retry_delay",
    "run_alert_cycle",
]
