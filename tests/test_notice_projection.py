import json

from test_boamp_notice_facts import extension, extract, record

from signals.api.notice_projection import project_notice_facts
from signals.billing.catalogue import entitlements_for


def facts_with_contacts():
    raw = record()
    companies = extension(raw)["efac:Organizations"]["efac:Organization"]
    for item in companies:
        company = item["efac:Company"]
        if company["cac:PartyIdentification"]["cbc:ID"] == "ORG-1":
            company["cac:Contact"]["cbc:ElectronicMail"] = "contact@example.com"
            company["cac:Contact"]["cbc:Telephone"] = "04 93 12 34 56"
    return extract(raw).awards[0]


def test_notice_projection_keeps_duration_without_start_and_separates_buyer():
    projection = project_notice_facts(
        facts_with_contacts(), entitlements=entitlements_for("essential")
    )
    assert projection["calendar"]["duration"]["value"] == "26.5"
    assert projection["calendar"]["duration"]["unit"] == "MONTH"
    assert projection["calendar"]["duration"]["scope"] == "contract"
    assert "start" not in json.dumps(projection["calendar"])
    assert projection["buyers"] == [{"name": "Collectivité exemple"}]
    assert projection["contacts"][0]["email"] == "contact@example.com"
    assert projection["contacts"][0]["phone"] == "04 93 12 34 56"
    assert "buyer@example" not in json.dumps(projection)
    assert "content_hash" not in json.dumps(projection)


def test_discovery_notice_contacts_never_leave_the_server():
    projection = project_notice_facts(
        facts_with_contacts(), entitlements=entitlements_for("discovery")
    )
    assert "contact@example.com" not in json.dumps(projection)
    assert "04 93" not in json.dumps(projection)
    assert projection["contacts"] == []
    assert "phone" in projection["available_contact_fields"]
    assert projection["publication_date"] == "2026-09-12"
    assert projection["awarded_amount"]["value"] == "1234567.8912"


def test_missing_duration_does_not_create_calendar_or_guessed_work_start():
    facts = facts_with_contacts().model_copy(update={"duration": None, "maximum_renewals": None})
    projection = project_notice_facts(facts, entitlements=entitlements_for("pro"))
    assert projection["calendar"] is None
