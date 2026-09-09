import pytest

from signals.campaigns.instantly import ShadowInstantlyProvider, ShadowSendForbidden


class Provider:
    def list_campaigns(self, *, search):
        return ()


def test_shadow_provider_rejects_every_send_mutation():
    provider = ShadowInstantlyProvider(Provider())
    with pytest.raises(ShadowSendForbidden):
        provider.create_lead_or_batch(provider_campaign_id="c", leads=())
    with pytest.raises(ShadowSendForbidden):
        provider.activate_campaign("c")
