"""Le contrat du vérificateur commercial (SPEC-009A §7, §11, §13–§15, §19–§27).

Ces tests portent sur la mécanique, pas sur le jugement du modèle : la vue
montrée, le schéma imposé, l'ancrage factuel, la politique finale, le cache, la
frontière fournisseur et la frontière produit/acquisition.

Aucun n'appelle Internet. Le double déterministe remplace le fournisseur.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest
from conftest import make_blind

from signals.verification import (
    POLICY_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    VerificationCache,
    apply_final_policy,
    build_verifier_input,
    validate_verification,
)
from signals.verification.cache import cache_key, icp_hash
from signals.verification.fake import FakeVerificationModel, approving_verification
from signals.verification.model import (
    CommercialVerification,
    verification_response_schema,
)
from signals.verification.prompt import (
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
    build_verification_prompt,
)
from signals.verification.protocol import ModelResponse
from signals.verification.runner import Candidate, verify_all, verify_candidate

VERIFICATION_PACKAGE = pathlib.Path("src/signals/verification")


class TestBlindView:
    def test_the_view_never_carries_an_engine_conclusion(self, blind: dict) -> None:
        """§13 — sans cela, le modèle vérifierait le score au lieu du signal."""
        view = build_verifier_input(blind)
        blob = json.dumps(view.as_dict(), ensure_ascii=False)
        for leaked in (
            "normalized_score",
            "raw_points",
            "score_components",
            "band",
            "decision",
            "rule_ids",
            "mechanism_facts",
            "pressure_facts",
            "gold",
            "expected_verdict",
        ):
            assert leaked not in blob, leaked

    def test_the_prompt_never_carries_an_engine_conclusion(self, blind: dict) -> None:
        prompt = build_verification_prompt(build_verifier_input(blind))
        for leaked in ("normalized_score", "raw_points", "score_components", "rule_ids"):
            assert leaked not in prompt, leaked

    def test_the_view_carries_everything_section_14_allows(self, blind: dict) -> None:
        """§14 — un vérificateur privé de ces champs jugerait à l'aveugle."""
        view = build_verifier_input(blind)
        assert view.signal_candidate_id
        assert view.winner["parties"][0]["members"][0]["legal_name"]
        for key in ("source", "publication_date", "title", "contract_type", "sector", "cpv_main"):
            assert view.award[key] is not None, key
        assert view.derived_needs[0]["statement"]
        assert view.derived_needs[0]["reasoning"]
        assert view.target_icp["primary_need_categories"]
        assert view.limitations["source_mode"] == "metadata_fallback"
        assert view.limitations["document_mode_disclosure"]
        assert view.fact_catalog

    def test_derived_needs_are_stripped_of_engine_internals(self, blind: dict) -> None:
        """§14 énumère six champs : les internes du Need Graph n'en font pas partie."""
        need = build_verifier_input(blind).derived_needs[0]
        assert set(need) == {
            "category",
            "statement",
            "reasoning",
            "timing",
            "externalisability",
            "confidence",
        }

    def test_the_missing_facts_are_named_rather_than_invented(self) -> None:
        """Un montant absent doit se dire absent — jamais se fabriquer."""
        view = build_verifier_input(make_blind(contract={"value": None}))
        assert "amount" in view.limitations["missing_facts"]
        assert any("Montant non publié" in fact.statement for fact in view.fact_catalog)

    def test_the_view_hash_is_stable_and_content_sensitive(self, blind: dict) -> None:
        """§11 — la clé de cache ne vaut que si l'empreinte suit le contenu."""
        first = build_verifier_input(blind).snapshot_hash()
        assert first == build_verifier_input(make_blind()).snapshot_hash()
        other = build_verifier_input(make_blind(contract={"title": "Autre marche"}))
        assert other.snapshot_hash() != first


class TestSchema:
    def test_the_provider_schema_is_strict_and_self_contained(self) -> None:
        """`strict: true` interdit les définitions externes et les champs optionnels."""
        schema = verification_response_schema()
        assert "$defs" not in schema
        assert "$ref" not in json.dumps(schema)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert len(schema["required"]) == 14

    def test_the_schema_is_derived_from_the_model_not_rewritten(self) -> None:
        """Un champ ajouté au modèle apparaît au schéma sans intervention."""
        schema = verification_response_schema()
        assert set(schema["properties"]) == set(CommercialVerification.model_fields)

    def test_every_enumeration_is_closed(self) -> None:
        schema = verification_response_schema()
        assert schema["properties"]["verdict"]["enum"] == [
            "approve",
            "downgrade",
            "reject",
            "insufficient_context",
        ]
        assert "enum" in schema["properties"]["blockers"]["items"]

    def test_an_out_of_vocabulary_value_is_refused_by_pydantic(self, blind: dict) -> None:
        """La seconde validation est la seule sur laquelle Kivou s'appuie."""
        view = build_verifier_input(blind)
        payload = approving_verification(view).model_dump()
        payload["verdict"] = "maybe"
        with pytest.raises(ValueError, match="verdict"):
            CommercialVerification.model_validate(payload)


class TestFactAnchoring:
    def test_a_cited_fact_must_exist(self, blind: dict) -> None:
        """§20 — c'est ce qui empêche le modèle de fabriquer un montant ou une date."""
        view = build_verifier_input(blind)
        verification = approving_verification(view, supporting_fact_ids=("F99",))
        outcome = validate_verification(verification, view)
        assert not outcome.valid
        assert any("inexistants" in error for error in outcome.errors)

    def test_a_limiting_fact_is_checked_too(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        verification = approving_verification(view, limiting_fact_ids=("F00",))
        assert not validate_verification(verification, view).valid

    def test_real_fact_ids_pass(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        assert validate_verification(approving_verification(view), view).valid


class TestOfferSummaryHasNoAuthority:
    """§15 — le texte libre clarifie, il n'élargit jamais."""

    def test_a_need_outside_the_structured_categories_cannot_be_approved(self) -> None:
        """Même si `offer_summary` semble couvrir le besoin, les catégories font foi."""
        blind = make_blind(
            derived_needs=[
                {
                    **make_blind()["derived_needs"][0],
                    "category": "waste_and_environment",
                }
            ],
            icp={
                **make_blind()["icp"],
                "offer_summary": "Nous faisons aussi de la gestion de dechets de chantier.",
            },
        )
        view = build_verifier_input(blind)
        outcome = validate_verification(approving_verification(view), view)
        assert not outcome.valid
        assert any("structurées" in error for error in outcome.errors)

    def test_a_secondary_category_is_still_a_structured_category(self) -> None:
        """Restreindre n'est pas exclure : le secondaire déclaré reste valable."""
        blind = make_blind(
            derived_needs=[
                {
                    **make_blind()["derived_needs"][0],
                    "category": "specialist_subcontracting",
                }
            ]
        )
        view = build_verifier_input(blind)
        assert validate_verification(approving_verification(view), view).valid

    def test_the_prompt_states_that_structured_fields_win(self, blind: dict) -> None:
        prompt = build_verification_prompt(build_verifier_input(blind))
        assert "offer_summary_clarification_only" in prompt
        assert "AUTORITÉ DES CHAMPS DE L'ICP" in prompt


class TestValidationCoherence:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("factual_consistency", "contradicted"),
            ("need_credibility", "unsupported"),
            ("icp_fit", "none"),
            ("actionability", "misleading"),
            ("specificity", "generic"),
            ("deliverable_overlap", "confirmed"),
            ("winner_already_provides_need", "yes"),
            ("timing_status", "stale"),
        ],
    )
    def test_approve_cannot_coexist_with_a_disqualifying_grade(
        self, blind: dict, field: str, value: str
    ) -> None:
        """§22 — un `approve` engage le feed ; il ne peut pas se contredire."""
        view = build_verifier_input(blind)
        verification = approving_verification(view, **{field: value})
        assert not validate_verification(verification, view).valid

    def test_approve_with_a_blocker_is_invalid(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        verification = approving_verification(view, blockers=("generic_signal",))
        assert not validate_verification(verification, view).valid

    def test_approve_without_a_supporting_fact_is_invalid(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        verification = approving_verification(view, supporting_fact_ids=())
        assert not validate_verification(verification, view).valid

    def test_a_reject_may_carry_any_grade_it_wants(self, blind: dict) -> None:
        """Les contrôles de §22 portent sur `approve` : un rejet motivé reste valide."""
        view = build_verifier_input(blind)
        verification = approving_verification(
            view,
            verdict="reject",
            need_credibility="contradicted",
            icp_fit="none",
            blockers=("deliverable_overlap",),
        )
        assert validate_verification(verification, view).valid


class TestFinalPolicy:
    def test_a_clean_approve_reaches_the_feed(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        verification = approving_verification(view)
        decision = apply_final_policy(verification, view, validate_verification(verification, view))
        assert decision.shows

    @pytest.mark.parametrize("verdict", ["downgrade", "reject", "insufficient_context"])
    def test_only_approve_reaches_the_feed(self, blind: dict, verdict: str) -> None:
        """§23 — pour le MVP, tout le reste est caché, sans file humaine."""
        view = build_verifier_input(blind)
        verification = approving_verification(view, verdict=verdict)
        decision = apply_final_policy(verification, view, validate_verification(verification, view))
        assert not decision.shows

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("icp_fit", "weak"),
            ("actionability", "too_weak"),
            ("specificity", "generic"),
            ("timing_status", "ending_soon"),
            ("deliverable_overlap", "suspected"),
            ("winner_already_provides_need", "possible"),
        ],
    )
    def test_the_policy_is_stricter_than_the_validator(
        self, blind: dict, field: str, value: str
    ) -> None:
        """`suspected` et `possible` passent la validation mais pas la politique.

        §22 invalide la contradiction franche ; §23 refuse en plus le doute. Un
        feed precision-first ne montre pas ce dont il n'est pas sûr.
        """
        view = build_verifier_input(blind)
        verification = approving_verification(view, **{field: value})
        decision = apply_final_policy(verification, view, validate_verification(verification, view))
        assert not decision.shows

    def test_a_validation_failure_never_reaches_the_feed(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        verification = approving_verification(view, supporting_fact_ids=("F99",))
        decision = apply_final_policy(verification, view, validate_verification(verification, view))
        assert not decision.shows
        assert decision.reason == "validation_failure"

    def test_an_api_failure_hides_without_blaming_the_signal(self, blind: dict) -> None:
        """§25 — le résultat opérationnel est HIDE, le diagnostic reste technique."""
        view = build_verifier_input(blind)
        decision = apply_final_policy(None, view, None, failure_kind="api_rate_limit")
        assert not decision.shows
        assert decision.reason == "api_rate_limit"


class TestCache:
    def test_the_key_changes_with_model_prompt_and_schema(self) -> None:
        """§11 — un changement de l'un d'eux invalide le cache sans intervention."""
        base = {
            "snapshot_hash": "s",
            "icp_hash": "i",
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "model_id": "deepseek/deepseek-v4-flash",
        }
        reference = cache_key(**base)
        assert cache_key(**{**base, "model_id": "other/model"}) != reference
        assert cache_key(**{**base, "prompt_version": "v9"}) != reference
        assert cache_key(**{**base, "schema_version": "v9"}) != reference
        assert cache_key(**{**base, "snapshot_hash": "other"}) != reference
        assert cache_key(**base) == reference

    def test_a_round_trip_returns_the_same_verification(
        self, blind: dict, tmp_path: pathlib.Path
    ) -> None:
        view = build_verifier_input(blind)
        cache = VerificationCache(tmp_path / "cache.json")
        verification = approving_verification(view)
        cache.put("k", verification)
        cache.flush()

        reloaded = VerificationCache(tmp_path / "cache.json")
        assert reloaded.get("k") == verification
        assert reloaded.hits == 1

    def test_the_cache_holds_no_secret(self, blind: dict, tmp_path: pathlib.Path) -> None:
        """§8 — aucune clé d'API ne doit pouvoir transiter par le cache."""
        view = build_verifier_input(blind)
        cache = VerificationCache(tmp_path / "cache.json")
        cache.put("k", approving_verification(view))
        cache.flush()
        blob = (tmp_path / "cache.json").read_text(encoding="utf-8")
        for secret in ("Authorization", "Bearer", "api_key", "OPENROUTER"):
            assert secret not in blob

    def test_the_cache_can_be_disabled(self, blind: dict, tmp_path: pathlib.Path) -> None:
        view = build_verifier_input(blind)
        cache = VerificationCache(tmp_path / "cache.json", enabled=False)
        cache.put("k", approving_verification(view))
        cache.flush()
        assert cache.get("k") is None
        assert not (tmp_path / "cache.json").exists()

    def test_the_cache_is_bounded(self, blind: dict, tmp_path: pathlib.Path) -> None:
        """Un cache sans plafond finirait par saturer un petit VPS."""
        view = build_verifier_input(blind)
        cache = VerificationCache(tmp_path / "cache.json", max_entries=2)
        for index in range(5):
            cache.put(f"k{index}", approving_verification(view))
        assert len(cache._entries) == 2
        assert cache.skipped_full == 3

    def test_an_unreadable_cache_is_an_empty_cache(self, tmp_path: pathlib.Path) -> None:
        """Un cache corrompu ne doit jamais faire échouer une course."""
        path = tmp_path / "cache.json"
        path.write_text("{ this is not json", encoding="utf-8")
        assert VerificationCache(path).get("k") is None

    def test_a_cache_hit_avoids_the_model_entirely(
        self, blind: dict, tmp_path: pathlib.Path
    ) -> None:
        view = build_verifier_input(blind)
        cache = VerificationCache(tmp_path / "cache.json")
        model = FakeVerificationModel()
        key = cache_key(
            snapshot_hash=view.snapshot_hash(),
            icp_hash=icp_hash(view.target_icp),
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            model_id=model.model_id,
        )
        cache.put(key, approving_verification(view))

        record = verify_candidate(Candidate(blind, "show"), model, cache=cache)
        assert model.calls == 0
        assert record.from_cache is True
        assert record.final_decision == "final_show"


class TestRunner:
    def test_only_show_and_borderline_may_enter(self, blind: dict) -> None:
        """§12 — les `exclude` ne sont pas envoyés au vérificateur en V0."""
        with pytest.raises(ValueError, match="show"):
            Candidate(blind, "exclude")

    def test_every_record_carries_its_full_provenance(self, blind: dict) -> None:
        """§27 — sans ces champs, un résultat ne serait pas rejouable."""
        record = verify_candidate(Candidate(blind, "show"), FakeVerificationModel())
        assert record.prompt_version == PROMPT_VERSION
        assert record.schema_version == SCHEMA_VERSION
        assert record.policy_version == POLICY_VERSION
        assert record.model_id and record.provider
        assert record.input_hash and record.created_at
        assert record.origin_decision == "show"

    def test_results_follow_input_order_whatever_the_concurrency(self, blind: dict) -> None:
        """Un banc dont la composition dépendrait des threads ne serait pas rejouable."""
        candidates = [
            Candidate(make_blind(signal_id=f"{index:064d}"), "show") for index in range(12)
        ]
        records, _ = verify_all(candidates, FakeVerificationModel(), max_workers=6)
        assert [record.signal_candidate_id for record in records] == [
            candidate.blind["signal_id"] for candidate in candidates
        ]

    def test_a_failure_is_counted_as_a_failure_not_as_a_rejection(self, blind: dict) -> None:
        model = FakeVerificationModel(default=ModelResponse(failure_kind="api_credit_failure"))
        records, usage = verify_all([Candidate(blind, "show")], model, max_workers=1)
        assert records[0].final_decision == "hide"
        assert records[0].failure_kind == "api_credit_failure"
        assert records[0].verification is None
        assert usage.failure_kinds["api_credit_failure"] == 1

    def test_a_response_carries_either_a_verification_or_a_failure(self) -> None:
        with pytest.raises(ValueError, match="jamais"):
            ModelResponse()


def _executable_strings(tree: ast.AST) -> list[str]:
    """Les chaînes qui vivent dans le code, docstrings exclues.

    Une docstring qui explique « ni OpenRouter, ni DeepSeek n'apparaissent ici »
    est de la documentation, pas un couplage. Ce qui compte est ce que le module
    importe et ce qu'il manipule.
    """
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings
    ]


class TestArchitecturalBoundaries:
    def test_the_domain_never_imports_a_provider(self) -> None:
        """§7 — hors de l'adaptateur, aucun module ne sait qu'un fournisseur existe."""
        for path in VERIFICATION_PACKAGE.glob("*.py"):
            if path.name in ("openrouter.py", "__init__.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            for module in imported:
                assert "httpx" not in module, f"{path.name} importe un transport HTTP"
                assert "openrouter" not in module, f"{path.name} importe l'adaptateur"

    def test_the_domain_manipulates_no_provider_string(self) -> None:
        """Une URL, une clé ou un en-tête d'autorisation n'ont rien à faire ici."""
        for path in VERIFICATION_PACKAGE.glob("*.py"):
            if path.name == "openrouter.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for value in _executable_strings(tree):
                lowered = value.lower()
                for forbidden in ("openrouter", "deepseek", "https://", "bearer", "authorization"):
                    assert forbidden not in lowered, f"{path.name} manipule {forbidden!r}"

    def test_the_adapter_is_the_only_module_that_reads_the_key(self) -> None:
        """§8 — une seule porte d'entrée pour le secret, et elle est nommée."""
        readers = [
            path.name
            for path in VERIFICATION_PACKAGE.glob("*.py")
            if "OPENROUTER_API_KEY" in path.read_text(encoding="utf-8")
        ]
        assert readers == ["openrouter.py"]

    def test_no_acquisition_engine_concept_enters_the_client_product(self) -> None:
        """§46 — SPEC-009A appartient au produit client, pas à l'acquisition."""
        forbidden = (
            "apollo",
            "instantly",
            "mailbox",
            "deliverability",
            "reply rate",
            "outbound",
            "campaign",
            "lead list",
        )
        for path in VERIFICATION_PACKAGE.glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                assert word not in text, f"{path.name} mentionne {word}"

    def test_no_contact_data_is_ever_shown_to_the_verifier(self, blind: dict) -> None:
        """Le signal s'arrête à l'entreprise gagnante — aucune personne n'entre."""
        blob = json.dumps(build_verifier_input(blind).as_dict(), ensure_ascii=False).lower()
        for field in ("email", "phone", "linkedin", "contact_person", "first_name"):
            assert f'"{field}"' not in blob

    def test_the_verifier_writes_no_client_facing_text(self, blind: dict) -> None:
        """§47 — le LLM ne rédige pas encore le signal ; il remplit un formulaire."""
        view = build_verifier_input(blind)
        verification = approving_verification(view)
        assert set(CommercialVerification.model_fields) == {
            "verdict",
            "factual_consistency",
            "need_credibility",
            "deliverable_overlap",
            "winner_already_provides_need",
            "icp_fit",
            "actionability",
            "specificity",
            "timing_status",
            "blockers",
            "supporting_fact_ids",
            "limiting_fact_ids",
            "confidence",
            "commercial_reason",
        }
        assert len(verification.commercial_reason) <= 400


class TestPromptHygiene:
    def test_source_content_is_fenced_as_untrusted(self, blind: dict) -> None:
        """§17 — tout texte de marché est une donnée, jamais une instruction."""
        prompt = build_verification_prompt(build_verifier_input(blind))
        assert UNTRUSTED_OPEN in prompt
        assert UNTRUSTED_CLOSE in prompt
        assert prompt.index(UNTRUSTED_OPEN) < prompt.index(UNTRUSTED_CLOSE)
        assert "aucune instruction" in prompt.lower()

    def test_the_mission_question_is_commercial_not_mechanical(self, blind: dict) -> None:
        """§18 — on ne demande pas si l'achat est certain."""
        prompt = build_verification_prompt(build_verifier_input(blind))
        assert "raison crédible" in prompt
        assert "Tu n'évalues PAS si l'achat est certain" in prompt

    def test_the_prompt_lists_only_citable_fact_ids(self, blind: dict) -> None:
        view = build_verifier_input(blind)
        prompt = build_verification_prompt(view)
        for fact in view.fact_catalog:
            assert fact.fact_id in prompt

    def test_no_source_text_escapes_the_untrusted_block(self, blind: dict) -> None:
        """Pas même l'énoncé d'un fait : le catalogue cite l'avis, il doit être enfermé.

        Sans ce test, le catalogue affiché avant le bloc rouvrirait le canal
        d'injection que le bloc referme.
        """
        view = build_verifier_input(blind)
        prompt = build_verification_prompt(view)
        trusted = prompt[: prompt.index(UNTRUSTED_OPEN)]
        assert view.award["title"] not in trusted
        assert view.award["factual_summary"] not in trusted
        for member in view.winner["parties"][0]["members"]:
            assert member["legal_name"] not in trusted
        # Les identifiants, eux, sont de nous : ils restent dans la consigne.
        for fact in view.fact_catalog:
            assert fact.fact_id in trusted
