from signals.api.commercial_context import commercial_context


def detail():
    return {
        "target_icp_id": "materials",
        "company": {"name": "Titulaire exemple"},
        "contract": {
            "lot_title": "Ouvrages béton",
            "title": "Génie civil",
            "location": {"locality": "Nice"},
        },
        "analysis": {
            "plausible_needs": {
                "items": [
                    {"category": "materials_or_components", "targeted_by_your_profile": True},
                    {"category": "workforce_capacity", "targeted_by_your_profile": False},
                ]
            }
        },
    }


def test_why_is_specific_to_selected_offer_without_unverified_purchase_promises():
    context = commercial_context(
        detail(),
        offers=("materials_and_components",),
        selected_offer="materials_and_components",
        lang="fr",
    )
    assert "matériaux et composants" in context["reason"]
    assert "Nice" in context["reason"] and "Ouvrages béton" in context["reason"]
    assert "main-d’œuvre" not in context["reason"]
    assert "va commander" not in context["reason"]
    assert "ne confirment" not in context["reason"]


def test_wrong_offer_or_unmatched_need_does_not_invent_relevance():
    assert (
        commercial_context(
            detail(),
            offers=("staffing_and_labour",),
            selected_offer="staffing_and_labour",
            lang="fr",
        )
        is None
    )
    assert (
        commercial_context(
            detail(),
            offers=("materials_and_components",),
            selected_offer="staffing_and_labour",
            lang="fr",
        )
        is None
    )


def test_english_context_is_english_and_no_empty_holder_is_fabricated():
    value = detail()
    value["company"]["name"] = None
    result = commercial_context(
        value, offers=("materials_and_components",), selected_offer=None, lang="en"
    )
    assert "materials and components" in result["reason"]
    assert "None" not in result["reason"]
