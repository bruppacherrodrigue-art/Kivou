"""La nomenclature CPV 2008 complète, importée une fois pour toutes.

Le jeu (`data/cpv_2008.json`) est committé — voir `SOURCE.md` — et ces tests
ne le régénèrent jamais depuis le CSV source (accès disque hors ligne, hors
du périmètre de `tests/`) : ils vérifient trois codes connus contre les
valeurs lues directement dans l'export.
"""

from __future__ import annotations

from signals.domain.cpv_labels import CPV_LABELS, cpv_label


def test_the_generated_dataset_holds_every_cpv_2008_code():
    assert len(CPV_LABELS) == 9454


def test_a_known_code_renders_its_exact_french_label():
    assert cpv_label("45262311", lang="fr") == "Travaux de gros œuvre en béton"


def test_a_known_code_renders_its_exact_english_label():
    assert cpv_label("19724000", lang="en") == "Synthetic monofilament"


def test_a_third_known_code_matches_the_csv_export():
    assert cpv_label("33710000", lang="fr") == "Parfums, produits de toilette et condoms"


def test_a_full_cpv_with_its_check_digit_is_normalized_to_eight_digits():
    assert cpv_label("45262311-4", lang="fr") == cpv_label("45262311", lang="fr")


def test_an_absent_code_falls_back_to_its_nearest_parent():
    # "45262399" n'existe pas dans le jeu ; son parent à 6 chiffres significatifs
    # ("452623" + "00") si.
    assert cpv_label("45262399", lang="fr") == cpv_label("45262300", lang="fr")
    assert cpv_label("45262399", lang="fr") is not None


def test_no_code_is_none():
    assert cpv_label(None, lang="fr") is None


def test_an_unsupported_language_falls_back_to_french():
    assert cpv_label("45262311", lang="de") == cpv_label("45262311", lang="fr")
    assert cpv_label("45262311", lang="klingon") == cpv_label("45262311", lang="fr")
