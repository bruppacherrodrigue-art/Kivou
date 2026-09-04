"""Le schéma relationnel — quatre tables, et la frontière qui les sépare.

    FAITS PUBLICS                          INFÉRENCES
    ─────────────                          ──────────
    source_event    la publication         materialized_signal
    contract_award  le contrat attribué      compréhension, besoins plausibles,
    evidence        l'ancrage vérifiable     pertinence ICP, score

Cette frontière est la doctrine du projet depuis SPEC-004, et elle devient ici
une propriété du stockage : trois tables ne contiennent que ce qu'un portail a
publié, une seule contient ce que Kivou en déduit. Un lecteur qui ouvre la base
sans connaître le code peut donc voir la distinction.

`FORBIDDEN_COLUMN_PATTERNS` la rend exécutable. Un nom de colonne survit à tous
les commentaires : c'est lui qu'un développeur pressé lira dans six mois, et
`confirmed_need` transformerait une hypothèse en promesse sans qu'aucune revue
ne s'en aperçoive.

    Portabilité (§3)
    ────────────────
    Déclaré en SQLAlchemy **Core** — tables et requêtes, jamais d'ORM. Le
    modèle canonique reste pydantic et souverain ; aucune classe du domaine ne
    devient une entité de base. Aucun type propre à un dialecte n'est employé :
    la production vise PostgreSQL, les tests tournent sur SQLite, et le DDL
    PostgreSQL est compilé dans la suite pour que la compatibilité soit
    vérifiée sans serveur.
"""

from __future__ import annotations

import sqlalchemy as sa

METADATA = sa.MetaData()

#: §5 — motifs de noms de colonnes qui affirmeraient un achat. Ils sont testés
#: contre chaque colonne du schéma, et contre les exemples que la SPEC nomme.
FORBIDDEN_COLUMN_PATTERNS: tuple[str, ...] = (
    r"confirmed",
    r"purchase_intent",
    r"will_buy",
    r"guaranteed",
    r"certain_",
    r"_certainty",
)

#: Les tables qui ne contiennent que ce qu'une source a publié, plus le
#: rattachement déterministe d'une représentation à son contrat réel.
FACT_TABLES: tuple[str, ...] = (
    "source_event",
    "contract_award",
    "evidence",
    "opportunity_representation",
    "procedure_documents",
)

#: Celles qui contiennent ce que Kivou en déduit.
INFERENCE_TABLES: tuple[str, ...] = ("materialized_signal",)

# Operational ingestion metadata is deliberately neither a source fact nor a
# commercial inference. Keeping it outside the two sets prevents audit helpers
# from assigning business semantics to scheduler state.
INGESTION_SOURCES: tuple[str, ...] = ("simap", "boamp", "decp", "ted")


def _created_at() -> sa.Column:
    """§3 — horodatage explicite, posé par l'application, jamais par la base.

    Un `server_default=now()` divergerait entre SQLite et PostgreSQL et rendrait
    les tests dépendants de l'horloge du moteur.
    """
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


source_event = sa.Table(
    "source_event",
    METADATA,
    # `EventRef.key()` — « système:notice:version ». Lisible, déterministe, et
    # déjà l'identité que le domaine utilise depuis SPEC-005.
    sa.Column("event_key", sa.String(256), primary_key=True),
    sa.Column("source_system", sa.String(32), nullable=False),
    sa.Column("source_notice_id", sa.String(256), nullable=False),
    sa.Column("notice_version", sa.String(32)),
    sa.Column("source_country", sa.String(2), nullable=False),
    sa.Column("source_procedure_id", sa.String(256)),
    sa.Column("source_url", sa.Text),
    sa.Column("event_type", sa.String(32), nullable=False),
    # Deux colonnes pour une seule date, et chacune a un rôle distinct :
    # `published_at_raw` conserve exactement ce que la source a publié — jour
    # seul ou instant horodaté, la distinction que `PublicationInstant` protège
    # depuis SPEC-005 — tandis que `published_on` porte le jour, seul filtrable.
    sa.Column("published_at_raw", sa.String(64)),
    sa.Column("published_on", sa.Date, index=True),
    sa.Column("published_precision", sa.String(16)),
    # Quand Kivou l'a appris. Distincte des trois horloges du contrat (§6).
    sa.Column("discovered_at", sa.DateTime(timezone=True)),
    sa.Column("procedure_buyers", sa.JSON, nullable=False),
    _created_at(),
)


procedure_documents = sa.Table(
    "procedure_documents",
    METADATA,
    sa.Column("procedure_document_key", sa.String(64), primary_key=True),
    sa.Column("source_system", sa.String(32), nullable=False, index=True),
    sa.Column("source_notice_id", sa.String(256), nullable=False, index=True),
    sa.Column("source_procedure_id", sa.String(256), index=True),
    sa.Column("buyer_fingerprint", sa.String(64), index=True),
    sa.Column("object_normalized", sa.Text),
    sa.Column("cpv_main", sa.String(8), index=True),
    sa.Column("submission_deadline", sa.DateTime(timezone=True), index=True),
    sa.Column("source_url", sa.Text, nullable=False),
    sa.Column("host", sa.String(255), nullable=False, index=True),
    sa.Column("access_status", sa.String(32), nullable=False, index=True),
    sa.Column("access_detail", sa.String(128)),
    sa.Column(
        "classified_requirements_count",
        sa.Integer,
        nullable=False,
        server_default="0",
    ),
    sa.Column("content_hash", sa.String(64)),
    sa.Column("media_type", sa.String(255)),
    sa.Column("byte_size", sa.BigInteger, nullable=False),
    sa.Column("archive_content", sa.LargeBinary),
    sa.Column("blocks", sa.JSON, nullable=False),
    sa.Column("join_status", sa.String(32), nullable=False, index=True),
    sa.Column("linked_award_key", sa.String(64), index=True),
    sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), index=True),
    _created_at(),
    sa.UniqueConstraint(
        "source_system", "source_notice_id", "source_url", "content_hash",
        name="uq_procedure_documents_source_version",
    ),
)


portal_capture_runtime = sa.Table(
    "portal_capture_runtime",
    METADATA,
    sa.Column("host", sa.String(255), primary_key=True),
    sa.Column("consecutive_errors", sa.Integer, nullable=False),
    sa.Column("last_request_at", sa.DateTime(timezone=True)),
    sa.Column("blocked_until", sa.DateTime(timezone=True), index=True),
    _created_at(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


contract_award = sa.Table(
    "contract_award",
    METADATA,
    sa.Column("award_key", sa.String(64), primary_key=True),
    sa.Column(
        "event_key",
        sa.String(256),
        sa.ForeignKey("source_event.event_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    # Identité telle que la source la publie — `None` quand elle n'en publie pas.
    sa.Column("source_award_id", sa.String(256)),
    sa.Column("lot_identifier", sa.String(256)),
    sa.Column("lot_title", sa.Text),
    sa.Column("contract_reference", sa.Text),
    # Objet
    sa.Column("title", sa.Text),
    sa.Column("description", sa.Text),
    sa.Column("cpv_main", sa.String(8), index=True),
    sa.Column("cpv_check_digit", sa.String(1)),
    sa.Column("cpv_additional", sa.JSON, nullable=False),
    # Argent — `Numeric` sans float : un montant perdu au centime est un fait faux.
    sa.Column("amount", sa.Numeric(18, 2)),
    sa.Column("currency", sa.String(3)),
    sa.Column("vat_category", sa.String(32)),
    # Parties
    sa.Column("winner_status", sa.String(16), nullable=False),
    sa.Column("awardee_parties", sa.JSON, nullable=False),
    sa.Column("contract_signatories", sa.JSON, nullable=False),
    # Géographie — la charge complète, plus le pays seul pour filtrer (§10).
    sa.Column("place_of_performance", sa.JSON),
    sa.Column("place_country", sa.String(2), index=True),
    # §6 — quatre horloges contractuelles, quatre colonnes. Les replier serait
    # exactement le défaut que SPEC-009E a corrigé.
    sa.Column("award_date", sa.Date, index=True),
    sa.Column("contract_signature_date", sa.Date),
    sa.Column("contract_notification_date", sa.Date, index=True),
    sa.Column("contract_start_date", sa.Date),
    sa.Column("contract_end_date", sa.Date),
    sa.Column("duration_value", sa.Integer),
    sa.Column("duration_unit", sa.String(16)),
    _created_at(),
)


evidence = sa.Table(
    "evidence",
    METADATA,
    sa.Column("evidence_key", sa.String(64), primary_key=True),
    sa.Column(
        "award_key",
        sa.String(64),
        sa.ForeignKey("contract_award.award_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    # Ce que cette preuve ancre : un fait du contrat, un besoin, un match.
    sa.Column("anchors_kind", sa.String(32), nullable=False),
    sa.Column("anchors_ref", sa.String(128), nullable=False),
    sa.Column("source_system", sa.String(32), nullable=False),
    sa.Column("source_kind", sa.String(32), nullable=False),
    sa.Column("source_notice_id", sa.String(256)),
    sa.Column("source_procedure_id", sa.String(256)),
    sa.Column("source_url", sa.Text),
    sa.Column("path", sa.Text),
    sa.Column("raw_value", sa.Text),
    sa.Column("excerpt", sa.Text),
    sa.Column("retrieved_at", sa.DateTime(timezone=True)),
    # Renseignée uniquement sur une preuve dérivée : un fait source n'a pas de
    # moteur derrière lui.
    sa.Column("engine_version", sa.String(64)),
    _created_at(),
)


opportunity_representation = sa.Table(
    "opportunity_representation",
    METADATA,
    # Une REPRÉSENTATION source appartient à exactement UNE opportunité — d'où
    # `award_key` en clé primaire. Une clé composite `(opportunity, award)`
    # aurait laissé la porte ouverte au même award rattaché à deux contrats,
    # c'est-à-dire au dédoublement silencieux qu'on cherche justement à
    # empêcher. Plusieurs représentations peuvent en revanche partager une
    # opportunité : c'est tout l'objet de la table.
    sa.Column(
        "award_key",
        sa.String(64),
        sa.ForeignKey("contract_award.award_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("opportunity_key", sa.String(64), nullable=False, index=True),
    _created_at(),
)


materialized_signal = sa.Table(
    "materialized_signal",
    METADATA,
    # Clé logique : cette OPPORTUNITÉ, pour ce client. Sans version de moteur (§7).
    sa.Column("signal_key", sa.String(64), primary_key=True),
    # Le contrat réel montré au client. Pour un marché mono-source il retombe
    # sur `award_key` ; pour un rapprochement fort BOAMP × DECP, les deux
    # représentations le partagent (closeout §2).
    sa.Column("opportunity_key", sa.String(64), nullable=False, index=True),
    # La représentation source qui a produit la RÉVISION COURANTE — et rien de
    # plus. Ce n'est PAS l'identité logique du signal : celle-ci est
    # `opportunity_key`. Le nom le dit, parce qu'un champ nommé `award_key` sur
    # une table de signaux invite à le prendre pour l'identité (closeout §6).
    # Les autres représentations restent lisibles via `opportunity_representation`.
    sa.Column(
        "materialization_award_key",
        sa.String(64),
        sa.ForeignKey("contract_award.award_key", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    # Closeout §3 — décision du superviseur : un signal appartient à un
    # `TargetICP` possédé par UN compte, jamais à un ICP partagé entre clients.
    # SPEC-011 ajoutera `account` et `target_icp(account_id, …)` sans toucher
    # cette table ; aucun `account_id` fictif n'est anticipé ici.
    sa.Column("target_icp_id", sa.String(128), nullable=False, index=True),
    # La version exacte du ciblage qui a produit cette correspondance. La ligne
    # survit aux changements d'ICP ; seules les lectures courantes exigent
    # qu'elle soit égale à `target_icp.matching_revision`.
    sa.Column("target_icp_revision", sa.Integer, nullable=False),
    sa.Column("invalidated_at", sa.DateTime(timezone=True), index=True),
    sa.Column("invalidation_reason", sa.String(64)),
    # §7 — le signal logique ne bouge pas ; sa révision suit son contenu.
    sa.Column("revision", sa.Integer, nullable=False),
    # Closeout §4 — empreinte déterministe de la charge matérialisée. C'est elle
    # qui décide d'une nouvelle révision, donc un changement d'inférence est
    # détecté même quand aucune version de moteur ne bouge.
    sa.Column("content_fingerprint", sa.String(64), nullable=False),
    # §6 et closeout §1 — les trois horloges survivent séparément au
    # rechargement. Le préfixe `materialized_` n'est pas décoratif : ces valeurs
    # décrivent l'INSTANTANÉ du jour de matérialisation, pas la fraîcheur
    # actuelle. Un signal `recent_award` figé le 18 août ne l'est plus le
    # 18 octobre, et une colonne nommée `recency_status` inviterait à l'oublier.
    sa.Column("materialized_recency_status", sa.String(32), nullable=False, index=True),
    sa.Column("materialized_primary_event", sa.String(32), index=True),
    sa.Column("materialized_award_clock_status", sa.String(16), nullable=False),
    sa.Column("materialized_notification_clock_status", sa.String(16), nullable=False),
    sa.Column("materialized_publication_clock_status", sa.String(16), nullable=False),
    sa.Column("materialized_award_age_days", sa.Integer),
    sa.Column("materialized_notification_age_days", sa.Integer),
    sa.Column("materialized_publication_age_days", sa.Integer),
    sa.Column("materialized_as_of", sa.Date, nullable=False),
    sa.Column("recency_policy_version", sa.String(64), nullable=False),
    # Identité du gagnant — dénormalisée pour l'affichage et le filtrage.
    sa.Column("winner_name", sa.Text),
    sa.Column("winner_country", sa.String(2)),
    sa.Column("winner_identifier_scheme", sa.String(64)),
    sa.Column("winner_identifier_value", sa.String(128), index=True),
    # Projection SaaS exacte et opaque, calculée depuis l'avis public. Elle
    # permet de retrouver les signaux d'une entreprise sans parcourir ceux du
    # compte et ne contient aucun nom, domaine ou identifiant fournisseur.
    sa.Column("company_identity_fingerprint", sa.String(64), index=True),
    # ── inférences, nommées comme telles ──────────────────────────────────────
    sa.Column("inferred_contract_type", sa.String(64)),
    sa.Column("inferred_sector", sa.String(64)),
    sa.Column("inferred_trade_domain", sa.String(64)),
    sa.Column("inferred_contract_summary", sa.Text),
    # Jamais `needs` tout court : le pluriel nu laisserait croire à un besoin établi.
    sa.Column("plausible_needs", sa.JSON, nullable=False),
    # Pertinence pour l'ICP — une décision de moteur, pas un fait du marché.
    sa.Column("icp_match_decision", sa.String(32)),
    sa.Column("icp_match_band", sa.String(32)),
    sa.Column("icp_match_confidence", sa.String(32)),
    sa.Column("icp_match_normalized_score", sa.Integer),
    sa.Column("icp_matched_needs", sa.JSON, nullable=False),
    # §8 — les versions qui ont produit ce signal, telles que les moteurs les
    # exposent. Aucune n'est codée en dur dans le schéma.
    sa.Column("engine_versions", sa.JSON, nullable=False),
    sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=False),
    _created_at(),
    # §7 et closeout §2, §3 — l'idempotence devient structurelle, et elle porte
    # sur l'OPPORTUNITÉ : deux représentations d'un même contrat ne peuvent pas
    # produire deux signaux pour le même client.
    sa.UniqueConstraint(
        "opportunity_key", "target_icp_id", name="uq_signal_opportunity_target_icp"
    ),
    sa.CheckConstraint("target_icp_revision >= 1", name="ck_signal_target_icp_revision"),
)


card_presentation_artifact = sa.Table(
    "card_presentation_artifact",
    METADATA,
    sa.Column("artifact_id", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "signal_key",
        sa.String(64),
        sa.ForeignKey("materialized_signal.signal_key", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("signal_revision", sa.Integer, nullable=False),
    sa.Column(
        "target_icp_id",
        sa.String(128),
        sa.ForeignKey("target_icp.target_icp_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("target_icp_revision", sa.Integer, nullable=False),
    sa.Column("artifact_kind", sa.String(32), nullable=False),
    sa.Column("language", sa.String(2), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("input_fingerprint", sa.String(64), nullable=False),
    sa.Column("payload", sa.JSON(none_as_null=True)),
    sa.Column("payload_variant", sa.String(32)),
    sa.Column("qa_status", sa.String(16), nullable=False),
    sa.Column("qa_reasons", sa.JSON(none_as_null=True), nullable=False),
    sa.Column("qa_policy_version", sa.String(128), nullable=False),
    sa.Column("generator_version", sa.String(128), nullable=False),
    sa.Column("prompt_version", sa.String(128)),
    sa.Column("model_id", sa.String(256)),
    sa.Column("provider", sa.String(128)),
    sa.Column("qa_model_id", sa.String(256)),
    sa.Column("qa_provider", sa.String(128)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("superseded_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint(
        "account_id",
        "signal_key",
        "target_icp_id",
        "artifact_kind",
        "language",
        "version",
        name="uq_card_presentation_version",
    ),
    sa.CheckConstraint(
        sa.column("artifact_id").regexp_match(r"^[0-9a-f]{64}$"),
        name="ck_card_presentation_artifact_id",
    ),
    sa.CheckConstraint(
        sa.column("input_fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
        name="ck_card_presentation_input_fingerprint",
    ),
    sa.CheckConstraint(
        "signal_revision >= 1",
        name="ck_card_presentation_signal_revision",
    ),
    sa.CheckConstraint(
        "target_icp_revision >= 1",
        name="ck_card_presentation_target_icp_revision",
    ),
    sa.CheckConstraint("version >= 1", name="ck_card_presentation_version"),
    sa.CheckConstraint(
        "artifact_kind = 'CARD_PRESENTATION'",
        name="ck_card_presentation_artifact_kind",
    ),
    sa.CheckConstraint(
        "language IN ('fr', 'en')",
        name="ck_card_presentation_language",
    ),
    sa.CheckConstraint(
        "qa_status IN ('PASS', 'REGENERATE', 'FALLBACK', 'REVIEW')",
        name="ck_card_presentation_qa_status",
    ),
    sa.CheckConstraint(
        sa.and_(
            sa.func.length(sa.column("qa_policy_version")).between(1, 128),
            sa.column("qa_policy_version").regexp_match(r"[0-9A-Za-z]"),
        ),
        name="ck_card_presentation_qa_policy_version",
    ),
    sa.CheckConstraint(
        sa.and_(
            sa.func.length(sa.column("generator_version")).between(1, 128),
            sa.column("generator_version").regexp_match(r"[0-9A-Za-z]"),
        ),
        name="ck_card_presentation_generator_version",
    ),
    sa.CheckConstraint(
        "payload_variant IS NULL OR payload_variant IN ('FULL', 'FACTUAL_FALLBACK')",
        name="ck_card_presentation_payload_variant",
    ),
    sa.CheckConstraint(
        "payload_variant IS NULL OR payload IS NOT NULL",
        name="ck_card_presentation_payload_binding",
    ),
    sa.CheckConstraint(
        "published_at IS NULL OR "
        "(payload IS NOT NULL AND payload_variant IS NOT NULL AND "
        "((qa_status = 'PASS' AND payload_variant = 'FULL') OR "
        "(qa_status = 'FALLBACK' AND payload_variant = 'FACTUAL_FALLBACK')))",
        name="ck_card_presentation_publishable_pair",
    ),
    sa.CheckConstraint(
        "qa_status <> 'FALLBACK' OR "
        "(provider IS NULL AND model_id IS NULL AND prompt_version IS NULL "
        "AND qa_provider IS NULL AND qa_model_id IS NULL)",
        name="ck_card_presentation_fallback_offline",
    ),
    sa.CheckConstraint(
        "published_at IS NULL OR created_at <= published_at",
        name="ck_card_presentation_created_published_order",
    ),
    sa.CheckConstraint(
        "superseded_at IS NULL OR "
        "(published_at IS NOT NULL AND published_at <= superseded_at)",
        name="ck_card_presentation_published_superseded_order",
    ),
    sa.Index(
        "ix_card_presentation_tenant_read",
        "account_id",
        "language",
        "artifact_kind",
        "signal_key",
        "signal_revision",
        "target_icp_revision",
    ),
    sa.Index(
        "uq_card_presentation_active_publication",
        "account_id",
        "signal_key",
        "target_icp_id",
        "artifact_kind",
        "language",
        unique=True,
        sqlite_where=sa.text("published_at IS NOT NULL AND superseded_at IS NULL"),
        postgresql_where=sa.text("published_at IS NOT NULL AND superseded_at IS NULL"),
    ),
)


ingestion_checkpoint = sa.Table(
    "ingestion_checkpoint",
    METADATA,
    sa.Column("source", sa.String(16), primary_key=True),
    sa.Column("cursor", sa.JSON),
    sa.Column("window_end", sa.DateTime(timezone=True)),
    sa.Column("last_started_at", sa.DateTime(timezone=True)),
    sa.Column("last_completed_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "source IN ('simap', 'boamp', 'decp', 'ted')",
        name="ck_ingestion_checkpoint_source",
    ),
)


ingestion_run = sa.Table(
    "ingestion_run",
    METADATA,
    sa.Column("run_id", sa.String(64), primary_key=True),
    sa.Column("source", sa.String(16), nullable=False, index=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(24), nullable=False, index=True),
    sa.Column("records_fetched", sa.Integer, nullable=False),
    sa.Column("records_accepted", sa.Integer, nullable=False),
    sa.Column("records_rejected", sa.Integer, nullable=False),
    sa.Column("records_persisted", sa.Integer, nullable=False),
    sa.Column("representations_linked", sa.Integer, nullable=False),
    sa.Column("opportunity_conflicts", sa.Integer, nullable=False),
    sa.Column("signals_materialized", sa.Integer, nullable=False),
    sa.Column("rate_limited_count", sa.Integer, nullable=False),
    sa.Column("error_category", sa.String(32)),
    sa.Column("error_message", sa.Text),
    sa.Column("checkpoint_before", sa.JSON),
    sa.Column("checkpoint_after", sa.JSON),
    sa.Column("dry_run", sa.Boolean, nullable=False),
    sa.CheckConstraint(
        "source IN ('simap', 'boamp', 'decp', 'ted')",
        name="ck_ingestion_run_source",
    ),
)


# Acquisition workflow memory is intentionally distinct from procurement
# `opportunity_key`. These tables are neither public-source facts nor customer
# signal inferences: they form the future Acquisition Engine's durable audit
# stream and current projection.
acquisition_opportunity = sa.Table(
    "acquisition_opportunity",
    METADATA,
    sa.Column("acquisition_opportunity_id", sa.String(64), primary_key=True),
    sa.Column("identity_key", sa.String(256), nullable=False, unique=True),
    sa.Column("state", sa.String(32), nullable=False, index=True),
    sa.Column("stream_version", sa.Integer, nullable=False),
    sa.Column("state_machine_version", sa.String(64), nullable=False),
    sa.Column("signal_ref", sa.String(256), nullable=False),
    sa.Column("supplier_ref", sa.String(256)),
    sa.Column("contact_ref", sa.String(256)),
    sa.Column("campaign_ref", sa.String(256)),
    sa.Column("decision", sa.String(16)),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("confidence", sa.Numeric(5, 4)),
    sa.Column("evidence_refs", sa.JSON, nullable=False),
    sa.Column("next_action", sa.String(100)),
    sa.Column("next_review_at", sa.DateTime(timezone=True), index=True),
    sa.Column("retry_count", sa.Integer, nullable=False),
    sa.Column("retry_at", sa.DateTime(timezone=True), index=True),
    sa.Column("last_error_category", sa.String(100)),
    sa.Column("policy_version", sa.String(100)),
    sa.Column("skill_version", sa.String(100)),
    sa.Column("supervisor_version", sa.String(100)),
    sa.Column("estimated_cost", sa.Numeric(18, 6)),
    sa.Column("last_event_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("stream_version >= 1", name="ck_acquisition_opportunity_stream_version"),
    sa.CheckConstraint("retry_count >= 0", name="ck_acquisition_opportunity_retry_count"),
    sa.CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        name="ck_acquisition_opportunity_confidence",
    ),
    sa.CheckConstraint(
        "estimated_cost IS NULL OR estimated_cost >= 0",
        name="ck_acquisition_opportunity_estimated_cost",
    ),
)


acquisition_event = sa.Table(
    "acquisition_event",
    METADATA,
    sa.Column("event_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_opportunity.acquisition_opportunity_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    sa.Column("stream_sequence", sa.Integer, nullable=False),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("state_machine_version", sa.String(64), nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("actor_type", sa.String(16), nullable=False),
    sa.Column("actor_ref", sa.String(256)),
    sa.Column("idempotency_key", sa.String(128), nullable=False),
    sa.Column("semantic_fingerprint", sa.String(64), nullable=False),
    sa.Column("correlation_id", sa.String(64)),
    sa.Column("causation_id", sa.String(64)),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("evidence_refs", sa.JSON, nullable=False),
    sa.Column("policy_version", sa.String(100)),
    sa.Column("skill_version", sa.String(100)),
    sa.Column("supervisor_version", sa.String(100)),
    sa.Column("confidence", sa.Numeric(5, 4)),
    sa.Column("estimated_cost", sa.Numeric(18, 6)),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.UniqueConstraint(
        "acquisition_opportunity_id",
        "stream_sequence",
        name="uq_acquisition_event_stream_sequence",
    ),
    sa.UniqueConstraint(
        "acquisition_opportunity_id",
        "idempotency_key",
        name="uq_acquisition_event_idempotency",
    ),
    sa.CheckConstraint("stream_sequence >= 1", name="ck_acquisition_event_stream_sequence"),
    sa.CheckConstraint("schema_version >= 1", name="ck_acquisition_event_schema_version"),
    sa.CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        name="ck_acquisition_event_confidence",
    ),
    sa.CheckConstraint(
        "estimated_cost IS NULL OR estimated_cost >= 0",
        name="ck_acquisition_event_estimated_cost",
    ),
)


# SPEC-019: narrow append-only policy control history and universal evaluation
# journal. These are authorization records, not an executor queue or Event Bus.
acquisition_policy_snapshot = sa.Table(
    "acquisition_policy_snapshot",
    METADATA,
    sa.Column("policy_snapshot_id", sa.String(64), primary_key=True),
    sa.Column("control_revision", sa.Integer, nullable=False, unique=True),
    sa.Column("policy_version", sa.String(64), nullable=False),
    sa.Column("autonomy_mode", sa.String(32), nullable=False),
    sa.Column("shadow_target_mode", sa.String(32)),
    sa.Column("read_only", sa.Boolean, nullable=False),
    sa.Column("kill_switch", sa.Boolean, nullable=False),
    sa.Column("qa_signal_ref", sa.String(256)),
    sa.Column("allowed_commands", sa.JSON, nullable=False),
    sa.Column("allowed_countries", sa.JSON, nullable=False),
    sa.Column("allowed_languages", sa.JSON, nullable=False),
    sa.Column("allowed_wedges", sa.JSON, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("daily_cost_cap", sa.Numeric(18, 6), nullable=False),
    sa.Column("daily_volume_cap", sa.Integer, nullable=False),
    sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("snapshot_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_by_actor_type", sa.String(16), nullable=False),
    sa.Column("created_by_actor_ref", sa.String(256), nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.CheckConstraint("control_revision >= 1", name="ck_policy_snapshot_revision"),
    sa.CheckConstraint("daily_cost_cap >= 0", name="ck_policy_snapshot_cost"),
    sa.CheckConstraint("daily_volume_cap >= 0", name="ck_policy_snapshot_volume"),
    sa.CheckConstraint(
        "expires_at IS NULL OR expires_at > effective_at",
        name="ck_policy_snapshot_interval",
    ),
)


policy_evaluation = sa.Table(
    "policy_evaluation",
    METADATA,
    sa.Column("evaluation_id", sa.String(64), primary_key=True),
    sa.Column("request_id", sa.String(128), nullable=False),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
    ),
    sa.Column("command", sa.String(64), nullable=False),
    sa.Column("target_ref", sa.String(256), nullable=False),
    sa.Column("action_fingerprint", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("counterfactual_status", sa.String(32)),
    sa.Column("executable", sa.Boolean, nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("policy_version", sa.String(64), nullable=False),
    sa.Column(
        "policy_snapshot_id",
        sa.String(64),
        sa.ForeignKey("acquisition_policy_snapshot.policy_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("control_revision", sa.Integer, nullable=False),
    sa.Column("runtime_revision", sa.String(100), nullable=False),
    sa.Column("evidence_refs", sa.JSON, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("estimated_cost", sa.Numeric(18, 6), nullable=False),
    sa.Column("proposed_volume", sa.Integer, nullable=False),
    sa.Column("cost_remaining", sa.Numeric(18, 6), nullable=False),
    sa.Column("volume_remaining", sa.Integer, nullable=False),
    sa.Column("approval_refs", sa.JSON, nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("valid_until", sa.DateTime(timezone=True)),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
    sa.Column("requires_revalidation", sa.Boolean, nullable=False),
    sa.Column("semantic_fingerprint", sa.String(64), nullable=False),
    sa.CheckConstraint("estimated_cost >= 0", name="ck_policy_evaluation_cost"),
    sa.CheckConstraint("proposed_volume >= 0", name="ck_policy_evaluation_volume"),
    sa.Index(
        "ix_policy_evaluation_opportunity_time",
        "acquisition_opportunity_id",
        "evaluated_at",
    ),
    sa.Index("ix_policy_evaluation_command_time", "command", "evaluated_at"),
)


# SPEC-020: Kivou-owned company identity and one narrow Apollo execution audit.
# No person/contact data and no provider payload are stored here.
acquisition_supplier = sa.Table(
    "acquisition_supplier",
    METADATA,
    sa.Column("supplier_ref", sa.String(64), primary_key=True),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("provider_organization_id", sa.String(128), nullable=False),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("normalized_name", sa.Text, nullable=False),
    sa.Column("primary_domain", sa.String(253), index=True),
    sa.Column("website_url", sa.Text),
    sa.Column("linkedin_company_url", sa.Text),
    sa.Column("country_code", sa.String(2)),
    sa.Column("location", sa.Text),
    sa.Column("industry", sa.Text),
    sa.Column("identity_status", sa.String(32), nullable=False),
    sa.Column("identity_conflict_fingerprint", sa.String(64), index=True),
    sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source_fingerprint", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "provider",
        "provider_organization_id",
        name="uq_acquisition_supplier_provider_identity",
    ),
    sa.CheckConstraint(
        "identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
        name="ck_acquisition_supplier_identity_status",
    ),
)


supplier_discovery_run = sa.Table(
    "supplier_discovery_run",
    METADATA,
    sa.Column("discovery_run_id", sa.String(64), primary_key=True),
    sa.Column("signal_ref", sa.String(256), nullable=False),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("search_profile_version", sa.String(64), nullable=False),
    sa.Column("search_profile_fingerprint", sa.String(64), nullable=False),
    sa.Column("search_profile", sa.JSON, nullable=False),
    sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
    sa.Column("requested_max_pages", sa.Integer, nullable=False),
    sa.Column("per_page", sa.Integer, nullable=False),
    sa.Column("candidate_cap", sa.Integer, nullable=False),
    sa.Column("planned_provider_credit_units", sa.Integer, nullable=False),
    sa.Column("pages_requested", sa.Integer, nullable=False),
    sa.Column(
        "recovery_provider_calls",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("provider_credit_units_observed", sa.Integer),
    sa.Column("provider_total_entries", sa.Integer),
    sa.Column("partial_results_only", sa.Boolean),
    sa.Column("records_returned", sa.Integer, nullable=False),
    sa.Column("records_accepted", sa.Integer, nullable=False),
    sa.Column("records_rejected", sa.Integer, nullable=False),
    sa.Column("rejection_reason_counts", sa.JSON, nullable=False),
    sa.Column("duplicates", sa.Integer, nullable=False),
    sa.Column("opportunities_created", sa.Integer, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("error_category", sa.String(64)),
    sa.Column("error_detail", sa.String(512)),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.CheckConstraint(
        "status IN ('STARTED', 'SUCCESS', 'PARTIAL', 'FAILED', 'SEARCH_TOO_BROAD')",
        name="ck_supplier_discovery_run_status",
    ),
    sa.CheckConstraint(
        "requested_max_pages >= 1 AND requested_max_pages <= 5",
        name="ck_supplier_discovery_run_pages",
    ),
    sa.CheckConstraint(
        "per_page >= 1 AND per_page <= 100", name="ck_supplier_discovery_run_per_page"
    ),
    sa.CheckConstraint(
        "candidate_cap >= 1 AND candidate_cap <= 500",
        name="ck_supplier_discovery_run_candidate_cap",
    ),
    sa.CheckConstraint(
        "planned_provider_credit_units >= 0 AND pages_requested >= 0",
        name="ck_supplier_discovery_run_credit_counts",
    ),
    sa.CheckConstraint(
        "recovery_provider_calls >= 0 AND recovery_provider_calls <= 1",
        name="ck_supplier_discovery_run_recovery_calls",
    ),
    sa.CheckConstraint(
        "provider_credit_units_observed IS NULL OR provider_credit_units_observed >= 0",
        name="ck_supplier_discovery_run_observed_credits",
    ),
    sa.CheckConstraint(
        "provider_total_entries IS NULL OR provider_total_entries >= 0",
        name="ck_supplier_discovery_run_provider_total",
    ),
    sa.CheckConstraint(
        "records_returned >= 0 AND records_accepted >= 0 "
        "AND records_rejected >= 0 AND duplicates >= 0 "
        "AND opportunities_created >= 0",
        name="ck_supplier_discovery_run_record_counts",
    ),
    sa.Index("ix_supplier_discovery_run_signal_time", "signal_ref", "started_at"),
    sa.Index("ix_supplier_discovery_run_status_time", "status", "started_at"),
)


# SPEC-021: selected provider-verified business-contact identity and one narrow
# People Search/Enrichment execution audit. Search candidates and raw Apollo
# responses are deliberately not persisted.
acquisition_contact = sa.Table(
    "acquisition_contact",
    METADATA,
    sa.Column("contact_ref", sa.String(64), primary_key=True),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("provider_person_id", sa.String(128), nullable=False),
    sa.Column("provider_organization_id", sa.String(128), nullable=False),
    sa.Column("first_name", sa.Text),
    sa.Column("last_name", sa.Text),
    sa.Column("display_name", sa.Text),
    sa.Column("title", sa.Text),
    sa.Column("normalized_title", sa.Text, nullable=False),
    sa.Column("role_profile_version", sa.String(64), nullable=False),
    sa.Column("role_tier", sa.Integer, nullable=False),
    sa.Column("business_email", sa.String(320), nullable=False),
    sa.Column("provider_email_status", sa.String(64), nullable=False),
    sa.Column("verification_state", sa.String(32), nullable=False),
    sa.Column("verification_provider", sa.String(32), nullable=False),
    sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("email_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source_fingerprint", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "provider",
        "provider_person_id",
        "supplier_ref",
        name="uq_acquisition_contact_provider_employment",
    ),
    sa.CheckConstraint("provider = 'apollo'", name="ck_acquisition_contact_provider"),
    sa.CheckConstraint(
        "verification_state = 'PROVIDER_VERIFIED'",
        name="ck_acquisition_contact_verification_state",
    ),
    sa.CheckConstraint(
        "verification_provider = 'apollo' AND provider_email_status = 'verified'",
        name="ck_acquisition_contact_verification_source",
    ),
    sa.CheckConstraint(
        "role_tier >= 1 AND role_tier <= 4", name="ck_acquisition_contact_role_tier"
    ),
    sa.Index(
        "ix_acquisition_contact_supplier_verification",
        "supplier_ref",
        "verification_state",
    ),
)


contact_discovery_run = sa.Table(
    "contact_discovery_run",
    METADATA,
    sa.Column("contact_discovery_run_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("search_profile_version", sa.String(64), nullable=False),
    sa.Column("search_profile_fingerprint", sa.String(64), nullable=False),
    sa.Column("search_profile", sa.JSON, nullable=False),
    sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
    sa.Column("expected_post_policy_version", sa.Integer, nullable=False),
    sa.Column("requested_max_pages", sa.Integer, nullable=False),
    sa.Column("per_page", sa.Integer, nullable=False),
    sa.Column("max_enrichment_attempts", sa.Integer, nullable=False),
    sa.Column("people_search_requests", sa.Integer, nullable=False),
    sa.Column(
        "recovery_provider_calls",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("provider_total_entries", sa.Integer),
    sa.Column("search_results_returned", sa.Integer, nullable=False),
    sa.Column("search_results_truncated", sa.Boolean, nullable=False),
    sa.Column("candidates_eligible", sa.Integer, nullable=False),
    sa.Column("candidates_rejected", sa.Integer, nullable=False),
    sa.Column("enrichment_attempts", sa.Integer, nullable=False),
    sa.Column("planned_provider_credit_units", sa.Integer, nullable=False),
    sa.Column("observed_provider_credit_units", sa.Integer),
    sa.Column("attempted_contact_refs", sa.JSON, nullable=False),
    sa.Column(
        "selected_contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
    ),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("error_category", sa.String(64)),
    sa.Column("error_detail", sa.String(512)),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.CheckConstraint("provider = 'apollo'", name="ck_contact_run_provider"),
    sa.CheckConstraint(
        "status IN ('STARTED', 'SUCCESS', 'NO_CANDIDATE', "
        "'NO_VERIFIED_CONTACT', 'CONTACT_SEARCH_TOO_BROAD', 'FAILED')",
        name="ck_contact_run_status",
    ),
    sa.CheckConstraint("expected_post_policy_version >= 2", name="ck_contact_run_expected_version"),
    sa.CheckConstraint(
        "requested_max_pages = 1 AND per_page >= 1 AND per_page <= 25 "
        "AND max_enrichment_attempts >= 1 AND max_enrichment_attempts <= 3",
        name="ck_contact_run_bounds",
    ),
    sa.CheckConstraint(
        "people_search_requests >= 0 AND search_results_returned >= 0 "
        "AND candidates_eligible >= 0 AND candidates_rejected >= 0 "
        "AND enrichment_attempts >= 0",
        name="ck_contact_run_counters",
    ),
    sa.CheckConstraint(
        "recovery_provider_calls >= 0 AND recovery_provider_calls <= 1",
        name="ck_contact_run_recovery_calls",
    ),
    sa.CheckConstraint(
        "provider_total_entries IS NULL OR provider_total_entries >= 0",
        name="ck_contact_run_provider_total",
    ),
    sa.CheckConstraint(
        "planned_provider_credit_units >= 0 AND "
        "(observed_provider_credit_units IS NULL OR observed_provider_credit_units >= 0)",
        name="ck_contact_run_credits",
    ),
    sa.Index(
        "ix_contact_discovery_run_opportunity_time",
        "acquisition_opportunity_id",
        "started_at",
    ),
    sa.Index("ix_contact_discovery_run_status_time", "status", "started_at"),
)


# SPEC-022: opportunity-scoped corporate research projection and one narrow
# exact-ID Apollo execution audit. No contact PII or raw provider payload.
acquisition_company_profile = sa.Table(
    "acquisition_company_profile",
    METADATA,
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("signal_ref", sa.String(256), nullable=False),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("provider_organization_id", sa.String(128), nullable=False),
    sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider_source_fingerprint", sa.String(64), nullable=False),
    sa.Column("provider_company_name", sa.Text, nullable=False),
    sa.Column("provider_primary_domain", sa.String(253)),
    sa.Column("provider_website_url", sa.Text),
    sa.Column("provider_country", sa.String(128)),
    sa.Column("provider_industry", sa.String(256)),
    sa.Column("provider_employee_count", sa.Integer),
    sa.Column("provider_founded_year", sa.Integer),
    sa.Column("provider_short_description", sa.Text),
    sa.Column("provider_keywords", sa.JSON, nullable=False),
    sa.Column("supplier_identity_status", sa.String(32), nullable=False),
    sa.Column("contact_role_profile_version", sa.String(64), nullable=False),
    sa.Column("contact_role_tier", sa.Integer, nullable=False),
    sa.Column("provider_research_status", sa.String(32), nullable=False),
    sa.Column("research_completeness", sa.String(16), nullable=False, index=True),
    sa.Column("research_gaps", sa.JSON, nullable=False),
    sa.Column("size_band", sa.String(16), nullable=False),
    sa.Column("size_band_version", sa.String(64), nullable=False),
    sa.Column("prebuild_version", sa.String(64), nullable=False),
    sa.Column("prebuild_fingerprint", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("provider = 'apollo'", name="ck_company_profile_provider"),
    sa.CheckConstraint(
        "supplier_identity_status IN ('PROVIDER_IDENTIFIED', 'DOMAIN_CONFLICT')",
        name="ck_company_profile_supplier_identity",
    ),
    sa.CheckConstraint(
        "provider_research_status = 'CURRENT_PROVIDER_RECORD'",
        name="ck_company_profile_provider_status",
    ),
    sa.CheckConstraint(
        "research_completeness IN ('COMPLETE', 'LIMITED')",
        name="ck_company_profile_completeness",
    ),
    sa.CheckConstraint(
        "size_band IN ('UNKNOWN', 'MICRO', 'SMB', 'MID_MARKET', 'ENTERPRISE')",
        name="ck_company_profile_size_band",
    ),
    sa.CheckConstraint(
        "provider_employee_count IS NULL OR "
        "(provider_employee_count >= 0 AND provider_employee_count <= 10000000)",
        name="ck_company_profile_employee_count",
    ),
    sa.CheckConstraint(
        "provider_founded_year IS NULL OR "
        "(provider_founded_year >= 1000 AND provider_founded_year <= 9999)",
        name="ck_company_profile_founded_year",
    ),
    sa.CheckConstraint(
        "contact_role_tier >= 1 AND contact_role_tier <= 4",
        name="ck_company_profile_role_tier",
    ),
    sa.Index(
        "ix_company_profile_completeness_updated",
        "research_completeness",
        "updated_at",
    ),
)


company_research_run = sa.Table(
    "company_research_run",
    METADATA,
    sa.Column("company_research_run_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("research_profile_version", sa.String(64), nullable=False),
    sa.Column("research_profile_fingerprint", sa.String(64), nullable=False),
    sa.Column("research_profile", sa.JSON, nullable=False),
    sa.Column("provider", sa.String(32), nullable=False),
    sa.Column("provider_endpoint_kind", sa.String(32), nullable=False),
    sa.Column("provider_request_fingerprint", sa.String(64), nullable=False),
    sa.Column("expected_post_policy_version", sa.Integer, nullable=False),
    sa.Column("planned_provider_credit_units", sa.Integer, nullable=False),
    sa.Column("observed_provider_credit_units", sa.Integer),
    sa.Column("provider_calls", sa.Integer, nullable=False),
    sa.Column(
        "recovery_provider_calls",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(16), nullable=False, index=True),
    sa.Column("error_category", sa.String(64)),
    sa.Column("error_detail", sa.String(512)),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.CheckConstraint("provider = 'apollo'", name="ck_company_run_provider"),
    sa.CheckConstraint(
        "provider_endpoint_kind = 'exact_organization_id'",
        name="ck_company_run_endpoint",
    ),
    sa.CheckConstraint(
        "status IN ('STARTED', 'SUCCESS', 'LIMITED', 'FAILED')",
        name="ck_company_run_status",
    ),
    sa.CheckConstraint("expected_post_policy_version >= 2", name="ck_company_run_expected_version"),
    sa.CheckConstraint(
        "planned_provider_credit_units = 1 AND provider_calls >= 0 AND provider_calls <= 1",
        name="ck_company_run_call_bound",
    ),
    sa.CheckConstraint(
        "recovery_provider_calls >= 0 AND recovery_provider_calls <= 1",
        name="ck_company_run_recovery_calls",
    ),
    sa.CheckConstraint(
        "observed_provider_credit_units IS NULL OR observed_provider_credit_units >= 0",
        name="ck_company_run_observed_credits",
    ),
    sa.Index(
        "ix_company_research_run_opportunity_time",
        "acquisition_opportunity_id",
        "started_at",
    ),
    sa.Index("ix_company_research_run_status_time", "status", "started_at"),
)


# SPEC-023: append-only deterministic proposal and policy disposition audit.
# No scores, narrative reasoning, customer state, or contact PII.
acquisition_decision_evaluation = sa.Table(
    "acquisition_decision_evaluation",
    METADATA,
    sa.Column("decision_evaluation_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("decision_input_version", sa.String(64), nullable=False),
    sa.Column("decision_input_fingerprint", sa.String(64), nullable=False),
    sa.Column("decision_input", sa.JSON, nullable=False),
    sa.Column("company_prebuild_fingerprint", sa.String(64), nullable=False),
    sa.Column("representative_award_key", sa.String(256), nullable=False),
    sa.Column("recency_basis", sa.String(32), nullable=False),
    sa.Column("recency_date", sa.Date),
    sa.Column("as_of_date", sa.Date, nullable=False),
    sa.Column("age_days", sa.Integer),
    sa.Column("decision_policy_version", sa.String(64), nullable=False),
    sa.Column("decision_policy_config_fingerprint", sa.String(64), nullable=False),
    sa.Column("proposed_decision", sa.String(16), nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("evidence_refs", sa.JSON, nullable=False),
    sa.Column("proposed_next_action", sa.String(100)),
    sa.Column("proposed_next_review_at", sa.DateTime(timezone=True)),
    sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
    sa.Column("policy_status", sa.String(32), nullable=False),
    sa.Column("policy_counterfactual_status", sa.String(32)),
    sa.Column("expected_post_policy_version", sa.Integer, nullable=False),
    sa.Column("disposition", sa.String(32), nullable=False, index=True),
    sa.Column(
        "recorded_event_id",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
        unique=True,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "proposed_decision IN ('SEND', 'REVIEW', 'NO_SEND')",
        name="ck_decision_eval_decision",
    ),
    sa.CheckConstraint(
        "disposition IN ('POLICY_BLOCKED', 'RECORDED')",
        name="ck_decision_eval_disposition",
    ),
    sa.CheckConstraint(
        "(disposition = 'RECORDED' AND recorded_event_id IS NOT NULL) OR "
        "(disposition = 'POLICY_BLOCKED' AND recorded_event_id IS NULL)",
        name="ck_decision_eval_recorded_event",
    ),
    sa.CheckConstraint(
        "(recency_basis = 'UNRESOLVED' AND recency_date IS NULL AND age_days IS NULL) OR "
        "(recency_basis IN ('AWARD_DATE', 'CONTRACT_NOTIFICATION_DATE', "
        "'PUBLICATION_DATE') AND recency_date IS NOT NULL AND age_days IS NOT NULL)",
        name="ck_decision_eval_recency",
    ),
    sa.CheckConstraint(
        "(proposed_decision = 'SEND' AND proposed_next_action = 'prepare_campaign') OR "
        "(proposed_decision = 'REVIEW' AND "
        "proposed_next_action = 'request_human_review') OR "
        "(proposed_decision = 'NO_SEND' AND proposed_next_action IS NULL)",
        name="ck_decision_eval_next_action",
    ),
    sa.CheckConstraint("proposed_next_review_at IS NULL", name="ck_decision_eval_no_hold_v1"),
    sa.CheckConstraint(
        "expected_post_policy_version >= 2", name="ck_decision_eval_expected_version"
    ),
    sa.Index(
        "ix_decision_evaluation_opportunity_time",
        "acquisition_opportunity_id",
        "created_at",
    ),
)


# SPEC-024: one immutable, purpose-limited acquisition copy artifact.  The
# rendered greeting can contain an optional first name; generic event/policy
# records intentionally do not carry it.
acquisition_personalization_artifact = sa.Table(
    "acquisition_personalization_artifact",
    METADATA,
    sa.Column("personalization_artifact_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "decision_evaluation_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_decision_evaluation.decision_evaluation_id", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    sa.Column("language", sa.String(2), nullable=False),
    sa.Column("input_version", sa.String(64), nullable=False),
    sa.Column("input_fingerprint", sa.String(64), nullable=False),
    sa.Column("eligibility_fingerprint", sa.String(64), nullable=False),
    sa.Column("need_engine_version", sa.String(64), nullable=False),
    sa.Column("selected_need_fingerprint", sa.String(64), nullable=False),
    sa.Column("template_version", sa.String(64), nullable=False),
    sa.Column("catalog_version", sa.String(64), nullable=False),
    sa.Column("language_policy_version", sa.String(64), nullable=False),
    sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
    sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
    sa.Column("artifact_fingerprint", sa.String(64), nullable=False),
    sa.Column("input_snapshot", sa.JSON, nullable=False),
    sa.Column("claim_map", sa.JSON, nullable=False),
    sa.Column("subject", sa.String(90)),
    sa.Column("greeting", sa.String(80)),
    sa.Column("body", sa.String(700)),
    sa.Column("cta", sa.String(256)),
    sa.Column("disposition", sa.String(32), nullable=False, index=True),
    sa.Column("policy_status", sa.String(32), nullable=False),
    sa.Column("policy_counterfactual_status", sa.String(32)),
    sa.Column(
        "recorded_event_id",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
        unique=True,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("language IN ('fr', 'en')", name="ck_personalization_language"),
    sa.CheckConstraint(
        "disposition IN ('READY', 'POLICY_BLOCKED')", name="ck_personalization_disposition"
    ),
    sa.CheckConstraint(
        "(disposition = 'READY' AND subject IS NOT NULL AND greeting IS NOT NULL AND body IS NOT NULL AND cta IS NOT NULL AND recorded_event_id IS NOT NULL) OR (disposition = 'POLICY_BLOCKED' AND subject IS NULL AND greeting IS NULL AND body IS NULL AND cta IS NULL AND recorded_event_id IS NULL)",
        name="ck_personalization_content",
    ),
    sa.Index("ix_personalization_opportunity_time", "acquisition_opportunity_id", "created_at"),
)


# SPEC-025: purpose-limited, append-only recipient suppression identity. Raw
# contact details never enter this cross-attempt hard-boundary table.
acquisition_contact_suppression = sa.Table(
    "acquisition_contact_suppression",
    METADATA,
    sa.Column("suppression_id", sa.String(64), primary_key=True),
    sa.Column("identity_hmac", sa.String(64), nullable=False),
    sa.Column("identity_key_version", sa.String(64), nullable=False),
    sa.Column("scope", sa.String(64), nullable=False),
    sa.Column("source", sa.String(32), nullable=False),
    sa.Column("reason_code", sa.String(100), nullable=False),
    sa.Column("evidence_ref", sa.String(256), nullable=False),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
    ),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("minimum_retention_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "supersedes_suppression_id",
        sa.String(64),
        sa.ForeignKey("acquisition_contact_suppression.suppression_id", ondelete="RESTRICT"),
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("scope = 'KIVOU_ACQUISITION_EMAIL'", name="ck_suppression_scope"),
    sa.CheckConstraint(
        "source IN ('UNSUBSCRIBE', 'RECIPIENT_OBJECTION', 'MANUAL_VERIFIED', 'SYSTEM_IMPORT')",
        name="ck_suppression_source",
    ),
    sa.CheckConstraint(
        "minimum_retention_until >= received_at", name="ck_suppression_retention_order"
    ),
    sa.Index("ix_contact_suppression_identity", "identity_key_version", "identity_hmac", "scope"),
)


# SPEC-025: immutable compliance proposal/policy/workflow audit. Rendered copy,
# raw provider payloads, contact PII, and legal narrative are deliberately absent.
acquisition_compliance_assessment = sa.Table(
    "acquisition_compliance_assessment",
    METADATA,
    sa.Column("compliance_assessment_id", sa.String(64), primary_key=True),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "personalization_artifact_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_personalization_artifact.personalization_artifact_id", ondelete="RESTRICT"
        ),
        nullable=False,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("jurisdiction", sa.String(64), nullable=False),
    sa.Column("jurisdiction_resolver_version", sa.String(64), nullable=False),
    sa.Column("ruleset_version", sa.String(64), nullable=False),
    sa.Column("ruleset_config_fingerprint", sa.String(64), nullable=False),
    sa.Column("input_version", sa.String(64), nullable=False),
    sa.Column("input_fingerprint", sa.String(64), nullable=False),
    sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
    sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("evidence_refs", sa.JSON, nullable=False),
    sa.Column("input_snapshot", sa.JSON, nullable=False),
    sa.Column("valid_until", sa.DateTime(timezone=True)),
    sa.Column("policy_status", sa.String(32), nullable=False),
    sa.Column("policy_counterfactual_status", sa.String(32)),
    sa.Column("expected_post_policy_version", sa.Integer, nullable=False),
    sa.Column("disposition", sa.String(32), nullable=False),
    sa.Column("next_action", sa.String(100)),
    sa.Column(
        "recorded_event_id",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
        unique=True,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "state IN ('ALLOWED', 'BLOCKED', 'REVIEW_REQUIRED', 'UNKNOWN')",
        name="ck_compliance_assessment_state",
    ),
    sa.CheckConstraint(
        "disposition IN ('RECORDED', 'POLICY_BLOCKED')", name="ck_compliance_assessment_disposition"
    ),
    sa.CheckConstraint(
        "(disposition = 'RECORDED' AND recorded_event_id IS NOT NULL) OR (disposition = 'POLICY_BLOCKED' AND recorded_event_id IS NULL)",
        name="ck_compliance_assessment_recorded_event",
    ),
    sa.CheckConstraint(
        "(state = 'ALLOWED' AND next_action IS NOT NULL AND next_action = 'schedule_campaign') OR (state = 'REVIEW_REQUIRED' AND next_action IS NOT NULL AND next_action = 'request_human_review') OR (state = 'UNKNOWN' AND (next_action = 'request_human_review' OR next_action IS NULL)) OR (state = 'BLOCKED' AND next_action IS NULL)",
        name="ck_compliance_assessment_next_action",
    ),
    sa.CheckConstraint(
        "(state = 'ALLOWED' AND valid_until IS NOT NULL) OR (state != 'ALLOWED' AND valid_until IS NULL)",
        name="ck_compliance_assessment_validity",
    ),
    sa.CheckConstraint(
        "expected_post_policy_version >= 2", name="ck_compliance_assessment_expected_version"
    ),
    sa.Index(
        "ix_compliance_assessment_opportunity_time", "acquisition_opportunity_id", "created_at"
    ),
)


# SPEC-026: PII-minimized Kivou micro-campaign identity and sealed batch state.
acquisition_campaign = sa.Table(
    "acquisition_campaign",
    METADATA,
    sa.Column("campaign_ref", sa.String(64), primary_key=True),
    sa.Column("campaign_group_key", sa.String(64), nullable=False),
    sa.Column("batch_generation", sa.Integer, nullable=False),
    sa.Column("factory_version", sa.String(64), nullable=False),
    sa.Column("plan_fingerprint", sa.String(64), nullable=False),
    sa.Column("country", sa.String(2), nullable=False),
    sa.Column("jurisdiction", sa.String(2), nullable=False),
    sa.Column("language", sa.String(2), nullable=False),
    sa.Column("wedge", sa.String(100), nullable=False),
    sa.Column("wedge_version", sa.String(64), nullable=False),
    sa.Column("selected_need_category", sa.String(100), nullable=False),
    sa.Column("selected_need_version", sa.String(64), nullable=False),
    sa.Column("personalization_catalog_version", sa.String(64), nullable=False),
    sa.Column("personalization_template_version", sa.String(64), nullable=False),
    sa.Column("language_policy_version", sa.String(64), nullable=False),
    sa.Column("envelope_catalog_version", sa.String(64), nullable=False),
    sa.Column("sender_profile_ref", sa.String(256), nullable=False),
    sa.Column("mailbox_pool_version", sa.String(64), nullable=False),
    sa.Column("compliance_ruleset_fingerprint", sa.String(64), nullable=False),
    sa.Column("sequence_policy_version", sa.String(64), nullable=False),
    sa.Column("tracking_policy_version", sa.String(64), nullable=False),
    sa.Column("send_window_policy_version", sa.String(64), nullable=False),
    sa.Column("sequence_window_policy_version", sa.String(64), nullable=False),
    sa.Column("batch_policy_version", sa.String(64), nullable=False),
    sa.Column("pacing_policy_version", sa.String(64), nullable=False),
    sa.Column("provider_workspace_ref", sa.String(128), nullable=False),
    sa.Column("provider_campaign_name", sa.String(100), nullable=False),
    sa.Column("provider_campaign_id", sa.String(128)),
    sa.Column("desired_provider_config_fingerprint", sa.String(64), nullable=False),
    sa.Column("current_provider_config_fingerprint", sa.String(64)),
    sa.Column("timezone", sa.String(64), nullable=False),
    sa.Column("step_1_execution_date", sa.Date, nullable=False),
    sa.Column("step_1_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("step_2_execution_date", sa.Date, nullable=False),
    sa.Column("step_2_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lifecycle", sa.String(16), nullable=False),
    sa.Column("reserved_member_count", sa.Integer, nullable=False),
    sa.Column("member_capacity", sa.Integer, nullable=False),
    sa.Column("first_member_reserved_at", sa.DateTime(timezone=True)),
    sa.Column("membership_close_at", sa.DateTime(timezone=True)),
    sa.Column("membership_closed_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "campaign_group_key", "batch_generation", name="uq_campaign_group_generation"
    ),
    sa.UniqueConstraint("provider_campaign_id", name="uq_campaign_provider_id"),
    sa.CheckConstraint("batch_generation >= 1", name="ck_campaign_batch_generation"),
    sa.CheckConstraint(
        "country IN ('CH', 'FR') AND jurisdiction IN ('CH', 'FR')",
        name="ck_campaign_country",
    ),
    sa.CheckConstraint("language IN ('fr', 'en')", name="ck_campaign_language"),
    sa.CheckConstraint(
        "lifecycle IN ('BUILDING', 'SEALED', 'ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED')",
        name="ck_campaign_lifecycle",
    ),
    sa.CheckConstraint(
        "member_capacity = 10 AND reserved_member_count >= 0 "
        "AND reserved_member_count <= member_capacity",
        name="ck_campaign_capacity",
    ),
    sa.CheckConstraint(
        "(first_member_reserved_at IS NULL AND membership_close_at IS NULL "
        "AND reserved_member_count = 0) OR "
        "(first_member_reserved_at IS NOT NULL AND membership_close_at IS NOT NULL "
        "AND reserved_member_count >= 1)",
        name="ck_campaign_membership_clock",
    ),
    sa.CheckConstraint(
        "membership_closed_at IS NULL OR membership_close_at IS NOT NULL",
        name="ck_campaign_membership_closed",
    ),
    sa.Index("ix_campaign_group_lifecycle", "campaign_group_key", "lifecycle"),
)


# Membership binds one opportunity to an exact sequence and safe Policy proof.
acquisition_campaign_member = sa.Table(
    "acquisition_campaign_member",
    METADATA,
    sa.Column("member_ref", sa.String(64), primary_key=True),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "supplier_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_supplier.supplier_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "personalization_artifact_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_personalization_artifact.personalization_artifact_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    sa.Column("personalization_artifact_fingerprint", sa.String(64), nullable=False),
    sa.Column(
        "compliance_assessment_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_compliance_assessment.compliance_assessment_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    sa.Column("compliance_assessment_fingerprint", sa.String(64), nullable=False),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("policy_provenance", sa.JSON, nullable=False),
    sa.Column("input_fingerprint", sa.String(64), nullable=False),
    sa.Column("contact_provider_identity_binding", sa.String(64), nullable=False),
    sa.Column("plan_fingerprint", sa.String(64), nullable=False),
    sa.Column("envelope_fingerprint", sa.String(64), nullable=False),
    sa.Column("policy_action_fingerprint", sa.String(64), nullable=False),
    sa.Column("ruleset_fingerprint", sa.String(64), nullable=False),
    sa.Column("sender_config_fingerprint", sa.String(64), nullable=False),
    sa.Column("mailbox_ref", sa.String(256), nullable=False),
    sa.Column("mailbox_readiness_fingerprint", sa.String(64), nullable=False),
    sa.Column("provider_lead_id", sa.String(128)),
    sa.Column("provider_binding_fingerprint", sa.String(64)),
    sa.Column("transport_recipient_identity", sa.String(64)),
    sa.Column("transport_recipient_key_version", sa.String(64)),
    sa.Column("step_1_execution_date", sa.Date, nullable=False),
    sa.Column("step_1_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("step_2_execution_date", sa.Date, nullable=False),
    sa.Column("step_2_authorization_deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("sequence_authorization_fingerprint", sa.String(64), nullable=False),
    sa.Column("step_1_sent_at", sa.DateTime(timezone=True)),
    sa.Column("step_2_due_at", sa.DateTime(timezone=True)),
    sa.Column("sequence_timing_fingerprint", sa.String(64)),
    sa.Column("execution_state", sa.String(16), nullable=False),
    sa.Column("sequence_state", sa.String(24), nullable=False),
    sa.Column("reason_code", sa.String(100)),
    sa.Column("incident_code", sa.String(100)),
    sa.Column("queue_event_id", sa.String(64), sa.ForeignKey("acquisition_event.event_id")),
    sa.Column("action_clear_event_id", sa.String(64), sa.ForeignKey("acquisition_event.event_id")),
    sa.Column("sent_event_id", sa.String(64), sa.ForeignKey("acquisition_event.event_id")),
    sa.Column("step_1_provider_event_ref", sa.String(64)),
    sa.Column("step_2_provider_event_ref", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("acquisition_opportunity_id", name="uq_campaign_member_opportunity"),
    sa.UniqueConstraint("provider_lead_id", name="uq_campaign_member_provider_lead"),
    sa.UniqueConstraint("policy_evaluation_id", name="uq_campaign_member_policy"),
    sa.CheckConstraint(
        "execution_state IN ('RESERVED', 'ENROLLED', 'QUEUED', 'STOPPED', 'SENT', 'FAILED')",
        name="ck_campaign_member_execution_state",
    ),
    sa.CheckConstraint(
        "sequence_state IN ('PENDING_STEP1', 'WAITING_STEP2', 'COMPLETED', 'STOPPED', 'FAILED')",
        name="ck_campaign_member_sequence_state",
    ),
    sa.CheckConstraint(
        "(sequence_timing_fingerprint IS NULL AND step_1_sent_at IS NULL "
        "AND step_2_due_at IS NULL) OR "
        "(sequence_timing_fingerprint IS NOT NULL AND step_1_sent_at IS NOT NULL "
        "AND step_2_due_at IS NOT NULL)",
        name="ck_campaign_member_timing_write",
    ),
    sa.CheckConstraint(
        "(transport_recipient_identity IS NULL AND "
        "transport_recipient_key_version IS NULL) OR "
        "(transport_recipient_identity IS NOT NULL AND "
        "transport_recipient_key_version IS NOT NULL)",
        name="ck_campaign_member_transport_identity",
    ),
    sa.Index("ix_campaign_member_campaign_state", "campaign_ref", "execution_state"),
    sa.Index(
        "ix_campaign_member_transport_identity",
        "campaign_ref",
        "transport_recipient_key_version",
        "transport_recipient_identity",
    ),
)


# Durable mutation ledger. A missing response is unknown remote state, never a rejection.
acquisition_provider_operation = sa.Table(
    "acquisition_provider_operation",
    METADATA,
    sa.Column("operation_ref", sa.String(64), primary_key=True),
    sa.Column("operation_key", sa.String(64), nullable=False, unique=True),
    sa.Column("operation_version", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "member_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign_member.member_ref", ondelete="RESTRICT"),
    ),
    sa.Column("desired_request_fingerprint", sa.String(64), nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("provider_identity", sa.String(128)),
    sa.Column("provider_result_fingerprint", sa.String(64)),
    sa.Column("lease_owner", sa.String(64)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    sa.Column("failed_at", sa.DateTime(timezone=True)),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
    sa.Column("error_code", sa.String(64)),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "kind IN ('CREATE_CAMPAIGN', 'CONFIGURE_CAMPAIGN', 'ADD_LEAD', "
        "'ACTIVATE_CAMPAIGN', 'PAUSE_CAMPAIGN', 'PAUSE_LEAD')",
        name="ck_provider_operation_kind",
    ),
    sa.CheckConstraint(
        "state IN ('PLANNED', 'IN_FLIGHT', 'CONFIRMED', 'RECONCILE_REQUIRED', "
        "'RETRYABLE_FAILED', 'TERMINAL_FAILED')",
        name="ck_provider_operation_state",
    ),
    sa.CheckConstraint(
        "(kind IN ('ADD_LEAD', 'PAUSE_LEAD') AND member_ref IS NOT NULL) OR "
        "(kind NOT IN ('ADD_LEAD', 'PAUSE_LEAD') AND member_ref IS NULL)",
        name="ck_provider_operation_member_scope",
    ),
    sa.CheckConstraint("attempt >= 0", name="ck_provider_operation_attempt"),
    sa.Index("ix_provider_operation_claim", "state", "retry_after", "lease_expires_at"),
)


# Deduplicated transport truth. Sensitive webhook content is transient only.
acquisition_provider_event = sa.Table(
    "acquisition_provider_event",
    METADATA,
    sa.Column("provider_event_ref", sa.String(64), primary_key=True),
    sa.Column("canonical_event_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("fingerprint_version", sa.String(64), nullable=False),
    sa.Column("fingerprint_key_version", sa.String(64), nullable=False),
    sa.Column("provider_event_type", sa.String(64), nullable=False),
    sa.Column("provider_workspace_ref", sa.String(128), nullable=False),
    sa.Column("provider_campaign_id", sa.String(128), nullable=False),
    sa.Column("provider_lead_id", sa.String(128)),
    sa.Column("provider_email_event_id", sa.String(128)),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "member_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign_member.member_ref", ondelete="RESTRICT"),
    ),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
    ),
    sa.Column("contact_ref", sa.String(64)),
    sa.Column("step", sa.Integer),
    sa.Column("variant", sa.String(32)),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("mailbox_ref", sa.String(256)),
    sa.Column("transport_status", sa.String(64)),
    sa.Column("resolution_state", sa.String(32), nullable=False),
    sa.Column("incident_code", sa.String(100)),
    sa.Column("recorded_acquisition_event_id", sa.String(64)),
    sa.CheckConstraint("step IS NULL OR step IN (1, 2)", name="ck_provider_event_step"),
    sa.CheckConstraint(
        "resolution_state IN ('ACCEPTED', 'PROCESSED', 'QUARANTINED', 'FAILED')",
        name="ck_provider_event_resolution",
    ),
    sa.Index("ix_provider_event_member_time", "member_ref", "occurred_at"),
)


# Immutable, append-auditable response evaluation. Reply content never enters this table.
acquisition_response_evaluation = sa.Table(
    "acquisition_response_evaluation",
    METADATA,
    sa.Column("response_evaluation_id", sa.String(64), primary_key=True),
    sa.Column("response_ref", sa.String(64), nullable=False),
    sa.Column(
        "provider_event_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_provider_event.provider_event_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "member_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign_member.member_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "contact_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact.contact_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("provider_email_id", sa.String(128)),
    sa.Column("provider_thread_id", sa.String(128)),
    sa.Column("input_source", sa.String(32), nullable=False),
    sa.Column("source_fingerprint", sa.String(64), nullable=False),
    sa.Column("content_fingerprint", sa.String(64)),
    sa.Column("content_fingerprint_version", sa.String(64)),
    sa.Column("content_fingerprint_key_version", sa.String(64)),
    sa.Column("resolver_version", sa.String(64), nullable=False),
    sa.Column("normalizer_version", sa.String(64), nullable=False),
    sa.Column("safety_version", sa.String(64), nullable=False),
    sa.Column("taxonomy_version", sa.String(64), nullable=False),
    sa.Column("classifier_version", sa.String(100), nullable=False),
    sa.Column("prompt_version", sa.String(100)),
    sa.Column("model_version", sa.String(100)),
    sa.Column("human_response_confirmed", sa.Boolean),
    sa.Column("classification", sa.String(32)),
    sa.Column("confidence", sa.Numeric(5, 4)),
    sa.Column("reason_codes", sa.JSON),
    sa.Column("hot_lead", sa.Boolean),
    sa.Column("review_required", sa.Boolean),
    sa.Column("next_action", sa.String(100)),
    sa.Column(
        "policy_evaluation_id",
        sa.String(64),
        sa.ForeignKey("policy_evaluation.evaluation_id", ondelete="RESTRICT"),
    ),
    sa.Column("policy_action_fingerprint", sa.String(64)),
    sa.Column("policy_status", sa.String(32)),
    sa.Column("estimated_cost", sa.Numeric(18, 6), nullable=False),
    sa.Column("actual_cost", sa.Numeric(18, 6)),
    sa.Column("input_tokens", sa.Integer),
    sa.Column("output_tokens", sa.Integer),
    sa.Column("processing_state", sa.String(16), nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("lease_owner", sa.String(64)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("retry_at", sa.DateTime(timezone=True)),
    sa.Column("failure_code", sa.String(100)),
    sa.Column("disposition", sa.String(64)),
    sa.Column(
        "outcome_event_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
    ),
    sa.Column(
        "next_action_event_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
    ),
    sa.Column(
        "suppression_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_contact_suppression.suppression_id", ondelete="RESTRICT"),
    ),
    sa.Column(
        "supersedes_response_evaluation_id",
        sa.String(64),
        sa.ForeignKey(
            "acquisition_response_evaluation.response_evaluation_id", ondelete="RESTRICT"
        ),
    ),
    sa.Column("reclassification_reason", sa.String(100)),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True)),
    sa.Column("finalized_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "provider_event_ref", "classifier_version", name="uq_response_event_classifier"
    ),
    sa.UniqueConstraint("response_ref", "classifier_version", name="uq_response_ref_classifier"),
    sa.CheckConstraint(
        "input_source IN ('WEBHOOK_V2', 'INSTANTLY_EMAIL_V2')",
        name="ck_response_input_source",
    ),
    sa.CheckConstraint(
        "processing_state IN ('PLANNED', 'IN_FLIGHT', 'RETRY_WAIT', 'FINALIZED')",
        name="ck_response_processing_state",
    ),
    sa.CheckConstraint(
        "classification IS NULL OR classification IN "
        "('POSITIVE', 'NEGATIVE', 'UNSUBSCRIBE', 'WRONG_PERSON', 'REFERRAL', "
        "'OUT_OF_OFFICE', 'AUTO_REPLY', 'COMPLAINT', 'SENSITIVE', 'AMBIGUOUS')",
        name="ck_response_classification",
    ),
    sa.CheckConstraint(
        "hot_lead IS NULL OR hot_lead IS FALSE OR "
        "(classification = 'POSITIVE' AND confidence >= 0.85 "
        "AND human_response_confirmed IS TRUE AND review_required IS TRUE "
        "AND next_action = 'request_human_review')",
        name="ck_response_hot_invariant",
    ),
    sa.CheckConstraint(
        "classification IS NULL OR classification NOT IN ('AUTO_REPLY', 'OUT_OF_OFFICE') OR "
        "(human_response_confirmed IS FALSE AND hot_lead IS FALSE AND outcome_event_ref IS NULL)",
        name="ck_response_machine_invariant",
    ),
    sa.CheckConstraint(
        "next_action IS NULL OR next_action = 'request_human_review'",
        name="ck_response_next_action",
    ),
    sa.CheckConstraint(
        "(content_fingerprint IS NULL AND content_fingerprint_version IS NULL "
        "AND content_fingerprint_key_version IS NULL) OR "
        "(content_fingerprint IS NOT NULL AND content_fingerprint_version IS NOT NULL "
        "AND content_fingerprint_key_version IS NOT NULL)",
        name="ck_response_content_fingerprint",
    ),
    sa.CheckConstraint(
        "(processing_state = 'FINALIZED' AND classification IS NOT NULL "
        "AND confidence IS NOT NULL AND reason_codes IS NOT NULL "
        "AND hot_lead IS NOT NULL AND review_required IS NOT NULL "
        "AND human_response_confirmed IS NOT NULL AND disposition IS NOT NULL "
        "AND evaluated_at IS NOT NULL AND finalized_at IS NOT NULL "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL) OR "
        "(processing_state <> 'FINALIZED' AND classification IS NULL "
        "AND confidence IS NULL AND reason_codes IS NULL AND hot_lead IS NULL "
        "AND review_required IS NULL AND human_response_confirmed IS NULL "
        "AND disposition IS NULL AND evaluated_at IS NULL AND finalized_at IS NULL)",
        name="ck_response_finalization",
    ),
    sa.CheckConstraint(
        "attempt >= 0 AND estimated_cost >= 0 "
        "AND (actual_cost IS NULL OR actual_cost >= 0) "
        "AND (input_tokens IS NULL OR input_tokens >= 0) "
        "AND (output_tokens IS NULL OR output_tokens >= 0)",
        name="ck_response_usage",
    ),
    sa.CheckConstraint(
        "(supersedes_response_evaluation_id IS NULL AND reclassification_reason IS NULL) OR "
        "(supersedes_response_evaluation_id IS NOT NULL "
        "AND reclassification_reason IS NOT NULL)",
        name="ck_response_reclassification",
    ),
    sa.Index("ix_response_claim", "processing_state", "retry_at", "lease_expires_at"),
    sa.Index("ix_response_member_received", "member_ref", "received_at"),
)


# SPEC-028: one immutable account attribution and one append-only milestone
# ledger.  Neither table stores the raw token, browser identifiers, contact
# details, campaign copy, nor Stripe payload/identifiers.
acquisition_conversion_journey = sa.Table(
    "acquisition_conversion_journey",
    METADATA,
    sa.Column("journey_ref", sa.String(64), primary_key=True),
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("source_click_event_ref", sa.String(64), nullable=False, index=True),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "member_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign_member.member_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("token_fingerprint", sa.String(64), nullable=False),
    sa.Column("token_version", sa.String(64), nullable=False),
    sa.Column("token_key_version", sa.String(100), nullable=False),
    sa.Column("country", sa.String(2), nullable=False),
    sa.Column("sector_ref", sa.String(256), nullable=False),
    sa.Column("sector_version", sa.String(100), nullable=False),
    sa.Column("need_ref", sa.String(256), nullable=False),
    sa.Column("need_version", sa.String(100), nullable=False),
    sa.Column("wedge", sa.String(100), nullable=False),
    sa.Column("wedge_version", sa.String(100), nullable=False),
    sa.Column("attribution_policy_version", sa.String(64), nullable=False),
    sa.Column("source_fingerprint", sa.String(64), nullable=False),
    sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("attribution_expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("signed_up_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("country IN ('CH', 'FR')", name="ck_conversion_journey_country"),
    sa.CheckConstraint(
        "clicked_at <= signed_up_at AND signed_up_at <= attribution_expires_at",
        name="ck_conversion_journey_window",
    ),
    sa.Index("ix_conversion_journey_campaign", "campaign_ref", "signed_up_at"),
)


acquisition_conversion_event = sa.Table(
    "acquisition_conversion_event",
    METADATA,
    sa.Column("conversion_event_ref", sa.String(64), primary_key=True),
    sa.Column(
        "journey_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_conversion_journey.journey_ref", ondelete="RESTRICT"),
    ),
    sa.Column("milestone", sa.String(32), nullable=False),
    sa.Column("event_version", sa.String(64), nullable=False),
    sa.Column("event_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("token_fingerprint", sa.String(64), index=True),
    sa.Column("trigger_ref_type", sa.String(64)),
    sa.Column("trigger_ref", sa.String(256)),
    sa.Column("account_id", sa.String(64), sa.ForeignKey("account.account_id")),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
    ),
    sa.Column(
        "member_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign_member.member_ref", ondelete="RESTRICT"),
    ),
    sa.Column(
        "acquisition_opportunity_id",
        sa.String(64),
        sa.ForeignKey("acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"),
    ),
    sa.Column("activation_fingerprint", sa.String(64)),
    sa.Column("billing_subscription_ref", sa.String(64)),
    sa.Column("catalogue_version", sa.String(64)),
    sa.Column("mrr_known", sa.Boolean),
    sa.Column("mrr_minor_units", sa.BigInteger),
    sa.Column("currency", sa.String(3)),
    sa.Column("reason_code", sa.String(100)),
    sa.Column(
        "outcome_event_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_event.event_id", ondelete="RESTRICT"),
    ),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "milestone IN ('CLICK', 'SIGNUP', 'ACTIVATED', 'PAID', 'MRR_CHANGED', "
        "'RETAINED_M1', 'RETAINED_M2', 'CHURNED')",
        name="ck_conversion_event_milestone",
    ),
    sa.CheckConstraint(
        "(milestone = 'CLICK' AND journey_ref IS NULL AND token_fingerprint IS NOT NULL "
        "AND account_id IS NULL) OR "
        "(milestone <> 'CLICK' AND journey_ref IS NOT NULL AND account_id IS NOT NULL)",
        name="ck_conversion_event_phase",
    ),
    sa.CheckConstraint(
        "(milestone = 'MRR_CHANGED' AND mrr_known IS NOT NULL) OR "
        "(milestone <> 'MRR_CHANGED' AND mrr_known IS NULL AND mrr_minor_units IS NULL "
        "AND currency IS NULL)",
        name="ck_conversion_event_mrr_scope",
    ),
    sa.CheckConstraint(
        "mrr_known IS NULL OR "
        "(mrr_known IS TRUE AND mrr_minor_units >= 0 AND currency IN ('chf', 'eur') "
        "AND reason_code IS NULL) OR "
        "(mrr_known IS FALSE AND mrr_minor_units IS NULL AND currency IS NULL "
        "AND reason_code IS NOT NULL)",
        name="ck_conversion_event_money",
    ),
    sa.CheckConstraint(
        "occurred_at <= observed_at AND observed_at <= recorded_at",
        name="ck_conversion_event_times",
    ),
    sa.Index("ix_conversion_event_journey_time", "journey_ref", "occurred_at"),
    sa.Index("ix_conversion_event_milestone_time", "milestone", "occurred_at"),
)


# SPEC-029: immutable country×wedge snapshots and bounded future-plan proposals.
acquisition_learning_snapshot = sa.Table(
    "acquisition_learning_snapshot",
    METADATA,
    sa.Column("snapshot_ref", sa.String(64), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
    sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("learning_version", sa.String(64), nullable=False),
    sa.Column("formula_version", sa.String(64), nullable=False),
    sa.Column("formula_fingerprint", sa.String(64), nullable=False),
    sa.Column("risk_policy_version", sa.String(64), nullable=False),
    sa.Column("risk_policy_fingerprint", sa.String(64), nullable=False),
    sa.Column("cost_policy_version", sa.String(64), nullable=False),
    sa.Column("cost_policy_fingerprint", sa.String(64), nullable=False),
    sa.Column("input_fingerprint", sa.String(64), nullable=False),
    sa.Column("cell_metrics", sa.JSON, nullable=False),
    sa.Column("allocation_envelope_version", sa.String(64), nullable=False),
    sa.Column("allocation_envelope_fingerprint", sa.String(64), nullable=False),
    sa.Column("current_allocation_fingerprint", sa.String(64), nullable=False),
    sa.Column("previous_applied_proposal_ref", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("window_start < window_end", name="ck_learning_snapshot_window"),
    sa.CheckConstraint("window_end <= captured_at", name="ck_learning_snapshot_capture"),
    sa.Index("ix_learning_snapshot_window", "window_end", "captured_at"),
)


acquisition_allocation_proposal = sa.Table(
    "acquisition_allocation_proposal",
    METADATA,
    sa.Column("proposal_ref", sa.String(64), primary_key=True),
    sa.Column(
        "snapshot_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_learning_snapshot.snapshot_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("proposal_version", sa.String(64), nullable=False),
    sa.Column("candidate_version", sa.String(64), nullable=False),
    sa.Column("allocation_envelope_fingerprint", sa.String(64), nullable=False),
    sa.Column("baseline_authority_ref", sa.String(256), nullable=False),
    sa.Column("current_allocation_fingerprint", sa.String(64), nullable=False),
    sa.Column("proposed_allocation_fingerprint", sa.String(64), nullable=False),
    sa.Column("current_allocation", sa.JSON, nullable=False),
    sa.Column("proposed_allocation", sa.JSON, nullable=False),
    sa.Column("from_country", sa.String(2)),
    sa.Column("from_wedge", sa.String(100)),
    sa.Column("to_country", sa.String(2)),
    sa.Column("to_wedge", sa.String(100)),
    sa.Column("delta_units", sa.Integer, nullable=False),
    sa.Column("expected_score_delta", sa.Numeric(24, 8), nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("confidence", sa.Numeric(5, 4)),
    sa.Column("selection_source", sa.String(32)),
    sa.Column("selection_reason_codes", sa.JSON),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("policy_evaluation_id", sa.String(64)),
    sa.Column("policy_action_fingerprint", sa.String(64)),
    sa.Column("policy_status", sa.String(32)),
    sa.Column("policy_counterfactual_status", sa.String(32)),
    sa.Column("decision_reason", sa.String(100)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True)),
    sa.Column("applied_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint("delta_units IN (0, 1)", name="ck_learning_proposal_delta"),
    sa.CheckConstraint(
        "state IN ('PROPOSED', 'SHADOW_ONLY', 'POLICY_DENIED', 'APPLIED', 'REJECTED')",
        name="ck_learning_proposal_state",
    ),
    sa.CheckConstraint(
        "selection_source IS NULL OR selection_source IN ('KIVOU_NO_CHANGE', 'HERMES')",
        name="ck_learning_proposal_selection",
    ),
    sa.CheckConstraint(
        "(selection_source IS NULL AND confidence IS NULL AND selection_reason_codes IS NULL) OR "
        "(selection_source IS NOT NULL AND confidence IS NOT NULL "
        "AND selection_reason_codes IS NOT NULL)",
        name="ck_learning_proposal_selection_fields",
    ),
    sa.CheckConstraint(
        "(delta_units = 0 AND from_country IS NULL AND from_wedge IS NULL "
        "AND to_country IS NULL AND to_wedge IS NULL) OR "
        "(delta_units = 1 AND from_country IS NOT NULL AND from_wedge IS NOT NULL "
        "AND to_country IS NOT NULL AND to_wedge IS NOT NULL)",
        name="ck_learning_proposal_cells",
    ),
    sa.CheckConstraint(
        "(state = 'APPLIED' AND decided_at IS NOT NULL AND applied_at IS NOT NULL) OR "
        "(state <> 'APPLIED' AND applied_at IS NULL)",
        name="ck_learning_proposal_application",
    ),
    sa.Index("ix_learning_proposal_snapshot", "snapshot_ref", "created_at"),
    sa.Index(
        "uq_learning_snapshot_selected_proposal",
        "snapshot_ref",
        unique=True,
        sqlite_where=sa.text("selection_source IS NOT NULL"),
        postgresql_where=sa.text("selection_source IS NOT NULL"),
    ),
    sa.Index(
        "uq_learning_applied_successor",
        "allocation_envelope_fingerprint",
        "baseline_authority_ref",
        unique=True,
        sqlite_where=sa.text("state = 'APPLIED'"),
        postgresql_where=sa.text("state = 'APPLIED'"),
    ),
)


# SPEC-031: durable acquisition-specific safety incidents and bounded dead letters.
acquisition_operational_incident = sa.Table(
    "acquisition_operational_incident",
    METADATA,
    sa.Column("incident_ref", sa.String(64), primary_key=True),
    sa.Column("trigger_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("incident_version", sa.String(64), nullable=False),
    sa.Column("incident_type", sa.String(64), nullable=False),
    sa.Column("severity", sa.String(16), nullable=False),
    sa.Column("scope_type", sa.String(16), nullable=False),
    sa.Column("scope_ref", sa.String(256), nullable=False),
    sa.Column("source_state_ref", sa.String(256), nullable=False),
    sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("observed_value", sa.Numeric(24, 8)),
    sa.Column("threshold_value", sa.Numeric(24, 8)),
    sa.Column("metric_version", sa.String(64)),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("human_review_required", sa.Boolean, nullable=False),
    sa.Column("pause_required", sa.Boolean, nullable=False),
    sa.Column("policy_control_before", sa.String(64)),
    sa.Column("policy_control_after", sa.String(64)),
    sa.Column(
        "campaign_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_campaign.campaign_ref", ondelete="RESTRICT"),
    ),
    sa.Column("mailbox_ref", sa.String(100)),
    sa.Column("wedge", sa.String(100)),
    sa.Column("country", sa.String(2)),
    sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "incident_type IN ('BOUNCE_RATE', 'COMPLAINT', 'COMPLIANCE_FAILURE', "
        "'PROVIDER_FAILURE', 'UNEXPECTED_TRANSPORT_TRUTH', 'BUDGET_BREACH', "
        "'COST_DRIFT', 'CONVERSION_DEGRADATION', 'RETENTION_DEGRADATION', "
        "'MAILBOX_UNAVAILABLE')",
        name="ck_operational_incident_type",
    ),
    sa.CheckConstraint(
        "severity IN ('WARNING', 'HIGH', 'CRITICAL')",
        name="ck_operational_incident_severity",
    ),
    sa.CheckConstraint(
        "scope_type IN ('GLOBAL', 'COUNTRY', 'WEDGE', 'CAMPAIGN', 'MAILBOX')",
        name="ck_operational_incident_scope",
    ),
    sa.CheckConstraint(
        "state IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')",
        name="ck_operational_incident_state",
    ),
    sa.CheckConstraint(
        "(state = 'OPEN' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR "
        "(state = 'ACKNOWLEDGED' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR "
        "(state = 'RESOLVED' AND resolved_at IS NOT NULL)",
        name="ck_operational_incident_lifecycle",
    ),
    sa.CheckConstraint(
        "country IS NULL OR country IN ('CH', 'FR')",
        name="ck_operational_incident_country",
    ),
    sa.Index(
        "ix_operational_incident_open_scope",
        "scope_type",
        "scope_ref",
        "severity",
        sqlite_where=sa.text("state <> 'RESOLVED'"),
        postgresql_where=sa.text("state <> 'RESOLVED'"),
    ),
    sa.Index("ix_operational_incident_campaign", "campaign_ref", "triggered_at"),
)


acquisition_dead_letter = sa.Table(
    "acquisition_dead_letter",
    METADATA,
    sa.Column("dead_letter_ref", sa.String(64), primary_key=True),
    sa.Column("exhaustion_fingerprint", sa.String(64), nullable=False, unique=True),
    sa.Column("work_type", sa.String(64), nullable=False),
    sa.Column("work_ref", sa.String(256), nullable=False),
    sa.Column("scope_type", sa.String(16), nullable=False),
    sa.Column("scope_ref", sa.String(256), nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("failure_code", sa.String(100), nullable=False),
    sa.Column("retry_policy_version", sa.String(64), nullable=False),
    sa.Column("source_component", sa.String(64), nullable=False),
    sa.Column("source_state_ref", sa.String(256), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("requeued_at", sa.DateTime(timezone=True)),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "work_type IN ('SUPERVISOR_CYCLE', 'SUPPLIER_DISCOVERY', "
        "'CONTACT_DISCOVERY', 'COMPANY_RESEARCH', 'CAMPAIGN_PROVIDER_OPERATION', "
        "'RESPONSE_RESOLUTION', 'CONVERSION_RECONCILIATION', 'LEARNING_CYCLE')",
        name="ck_dead_letter_work_type",
    ),
    sa.CheckConstraint(
        "scope_type IN ('GLOBAL', 'COUNTRY', 'WEDGE', 'CAMPAIGN', 'MAILBOX')",
        name="ck_dead_letter_scope",
    ),
    sa.CheckConstraint("attempt_count >= 1", name="ck_dead_letter_attempt_count"),
    sa.CheckConstraint(
        "first_failed_at <= last_failed_at",
        name="ck_dead_letter_failure_window",
    ),
    sa.CheckConstraint(
        "status IN ('OPEN', 'REQUEUED', 'RESOLVED')",
        name="ck_dead_letter_status",
    ),
    sa.CheckConstraint(
        "(status = 'OPEN' AND requeued_at IS NULL AND resolved_at IS NULL) OR "
        "(status = 'REQUEUED' AND requeued_at IS NOT NULL AND resolved_at IS NULL) OR "
        "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
        name="ck_dead_letter_lifecycle",
    ),
    sa.Index("ix_dead_letter_status_created", "status", "created_at"),
    sa.Index("ix_dead_letter_work", "work_type", "work_ref"),
)


# The acquisition runtime keeps orchestration metadata only. Provider payloads,
# recipients and message content remain in their existing bounded domain stores.
acquisition_runtime_lease = sa.Table(
    "acquisition_runtime_lease",
    METADATA,
    sa.Column("lease_name", sa.String(64), primary_key=True),
    sa.Column("owner_ref", sa.String(256)),
    sa.Column("acquired_at", sa.DateTime(timezone=True)),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.CheckConstraint("generation >= 0", name="ck_acquisition_runtime_lease_generation"),
    sa.CheckConstraint(
        "(owner_ref IS NULL AND acquired_at IS NULL AND heartbeat_at IS NULL "
        "AND expires_at IS NULL) OR "
        "(owner_ref IS NOT NULL AND acquired_at IS NOT NULL "
        "AND heartbeat_at IS NOT NULL AND expires_at IS NOT NULL "
        "AND acquired_at <= heartbeat_at AND heartbeat_at < expires_at)",
        name="ck_acquisition_runtime_lease_lifecycle",
    ),
)


acquisition_runtime_cycle = sa.Table(
    "acquisition_runtime_cycle",
    METADATA,
    sa.Column("cycle_ref", sa.String(64), primary_key=True),
    sa.Column("opportunity_key", sa.String(256), nullable=False),
    sa.Column("config_fingerprint", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("next_stage", sa.String(32)),
    sa.Column("spent_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("last_reason_code", sa.String(100)),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint(
        "opportunity_key",
        "config_fingerprint",
        name="uq_acquisition_runtime_cycle_config_opportunity",
    ),
    sa.CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', "
        "'FAILED', 'SUPPRESSED', 'CANCELLED')",
        name="ck_acquisition_runtime_cycle_status",
    ),
    sa.CheckConstraint(
        "next_stage IS NULL OR next_stage IN "
        "('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
        "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
        "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
        "'ATTRIBUTION_CONVERSION')",
        name="ck_acquisition_runtime_cycle_next_stage",
    ),
    sa.CheckConstraint("spent_cost >= 0", name="ck_acquisition_runtime_cycle_cost"),
    sa.CheckConstraint(
        "(status IN ('SUCCEEDED', 'SUPPRESSED') AND completed_at IS NOT NULL "
        "AND next_stage IS NULL) OR "
        "(status NOT IN ('SUCCEEDED', 'SUPPRESSED') AND completed_at IS NULL)",
        name="ck_acquisition_runtime_cycle_lifecycle",
    ),
    sa.Index("ix_acquisition_runtime_cycle_status", "status", "updated_at"),
)


acquisition_runtime_observation = sa.Table(
    "acquisition_runtime_observation",
    METADATA,
    sa.Column("runtime_name", sa.String(64), primary_key=True),
    sa.Column("capability_fingerprint", sa.String(64), nullable=False),
    sa.Column("environment", sa.String(16), nullable=False),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("qa_only", sa.Boolean, nullable=False),
    sa.Column("hermes_repository", sa.String(256), nullable=False),
    sa.Column("hermes_tag", sa.String(256), nullable=False),
    sa.Column("hermes_commit", sa.String(40), nullable=False),
    sa.Column("hermes_version", sa.String(256), nullable=False),
    sa.Column("hermes_python_contract", sa.String(256), nullable=False),
    sa.Column("registry_identity", sa.String(64), nullable=False),
    sa.Column("native_tools", sa.Integer, nullable=False),
    sa.Column("commands", sa.JSON, nullable=False),
    sa.Column("dependencies", sa.JSON, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "last_cycle_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="RESTRICT"),
    ),
    sa.Column("last_cycle_status", sa.String(16)),
    sa.Column("last_cycle_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "runtime_name = 'acquisition-run-once'",
        name="ck_acquisition_runtime_observation_name",
    ),
    sa.CheckConstraint(
        "mode = 'SHADOW' AND native_tools = 0 AND ("
        "(environment = 'STAGING' AND qa_only IS TRUE) OR "
        "(environment = 'PRODUCTION' AND qa_only IS FALSE))",
        name="ck_acquisition_runtime_observation_boundary",
    ),
    sa.CheckConstraint(
        "observed_at <= heartbeat_at AND heartbeat_at <= updated_at",
        name="ck_acquisition_runtime_observation_timeline",
    ),
    sa.CheckConstraint(
        "(last_cycle_ref IS NULL AND last_cycle_status IS NULL "
        "AND last_cycle_at IS NULL) OR "
        "(last_cycle_ref IS NOT NULL AND last_cycle_status IS NOT NULL "
        "AND last_cycle_at IS NOT NULL AND last_cycle_at <= heartbeat_at)",
        name="ck_acquisition_runtime_observation_cycle",
    ),
    sa.CheckConstraint(
        "last_cycle_status IS NULL OR last_cycle_status IN "
        "('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', "
        "'FAILED', 'SUPPRESSED', 'CANCELLED')",
        name="ck_acquisition_runtime_observation_cycle_status",
    ),
    sa.Index("ix_acquisition_runtime_observation_heartbeat", "heartbeat_at"),
)


acquisition_runtime_approval = sa.Table(
    "acquisition_runtime_approval",
    METADATA,
    sa.Column("approval_id", sa.String(64), primary_key=True),
    sa.Column("request_ref", sa.String(256), nullable=False, unique=True),
    sa.Column(
        "cycle_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("stage", sa.String(32), nullable=False),
    sa.Column("purpose", sa.String(32), nullable=False),
    sa.Column("command", sa.String(64), nullable=False),
    sa.Column("target_ref", sa.String(256), nullable=False),
    sa.Column("acquisition_opportunity_id", sa.String(256), nullable=False),
    sa.Column("action_fingerprint", sa.String(64), nullable=False),
    sa.Column("policy_version", sa.String(256), nullable=False),
    sa.Column("policy_snapshot_id", sa.String(256), nullable=False),
    sa.Column("control_revision", sa.Integer, nullable=False),
    sa.Column("scope_fingerprint", sa.String(64), nullable=False),
    sa.Column("binding_fingerprint", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("approved_by_actor_ref", sa.String(256)),
    sa.Column("approved_at", sa.DateTime(timezone=True)),
    sa.Column("consumed_by_ref", sa.String(256)),
    sa.Column("consumed_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
        "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
        "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
        "'ATTRIBUTION_CONVERSION')",
        name="ck_acquisition_runtime_approval_stage",
    ),
    sa.CheckConstraint(
        "purpose IN ('ACTION', 'COMPLIANCE_REVIEW')",
        name="ck_acquisition_runtime_approval_purpose",
    ),
    sa.CheckConstraint(
        "state IN ('PENDING', 'APPROVED', 'CONSUMED')",
        name="ck_acquisition_runtime_approval_state",
    ),
    sa.CheckConstraint(
        "control_revision >= 1",
        name="ck_acquisition_runtime_approval_revision",
    ),
    sa.CheckConstraint(
        "requested_at < expires_at AND updated_at >= requested_at",
        name="ck_acquisition_runtime_approval_window",
    ),
    sa.CheckConstraint(
        "(state = 'PENDING' AND approved_by_actor_ref IS NULL "
        "AND approved_at IS NULL AND consumed_by_ref IS NULL "
        "AND consumed_at IS NULL) OR "
        "(state = 'APPROVED' AND approved_by_actor_ref IS NOT NULL "
        "AND approved_at IS NOT NULL AND requested_at <= approved_at "
        "AND approved_at < expires_at AND consumed_by_ref IS NULL "
        "AND consumed_at IS NULL) OR "
        "(state = 'CONSUMED' AND approved_by_actor_ref IS NOT NULL "
        "AND approved_at IS NOT NULL AND consumed_by_ref IS NOT NULL "
        "AND consumed_at IS NOT NULL AND requested_at <= approved_at "
        "AND approved_at <= consumed_at AND consumed_at < expires_at)",
        name="ck_acquisition_runtime_approval_lifecycle",
    ),
    sa.Index(
        "ix_acquisition_runtime_approval_state_expiry",
        "state",
        "expires_at",
    ),
)


acquisition_runtime_stage = sa.Table(
    "acquisition_runtime_stage",
    METADATA,
    sa.Column(
        "cycle_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("stage", sa.String(32), primary_key=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("plan_ref", sa.String(256)),
    sa.Column("command", sa.String(64)),
    sa.Column("argument_fingerprint", sa.String(64)),
    sa.Column("result_refs", sa.JSON, nullable=False),
    sa.Column("reserved_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("observed_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("reason_codes", sa.JSON, nullable=False),
    sa.Column("retry_at", sa.DateTime(timezone=True)),
    sa.Column("replay_same_attempt", sa.Boolean, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
        "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
        "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
        "'ATTRIBUTION_CONVERSION')",
        name="ck_acquisition_runtime_stage_name",
    ),
    sa.CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', "
        "'FAILED', 'SUPPRESSED', 'CANCELLED')",
        name="ck_acquisition_runtime_stage_status",
    ),
    sa.CheckConstraint("attempt_count >= 0", name="ck_acquisition_runtime_stage_attempts"),
    sa.CheckConstraint(
        "reserved_cost >= 0 AND observed_cost >= 0",
        name="ck_acquisition_runtime_stage_cost",
    ),
    sa.CheckConstraint(
        "(status = 'PENDING' AND attempt_count = 0 AND started_at IS NULL "
        "AND completed_at IS NULL) OR "
        "(status = 'RUNNING' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND completed_at IS NULL) OR "
        "(status NOT IN ('PENDING', 'RUNNING') AND attempt_count >= 1 "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
        name="ck_acquisition_runtime_stage_lifecycle",
    ),
    sa.CheckConstraint(
        "retry_at IS NULL OR status = 'WAITING'",
        name="ck_acquisition_runtime_stage_retry",
    ),
    sa.CheckConstraint(
        "replay_same_attempt IS FALSE OR "
        "(status = 'WAITING' AND retry_at IS NOT NULL)",
        name="ck_acquisition_runtime_stage_replay",
    ),
    sa.Index("ix_acquisition_runtime_stage_status", "status", "updated_at"),
)


# Immutable cost ledger: the mutable stage checkpoint keeps only the latest
# attempt, while every finalized attempt remains chargeable across retries.
acquisition_runtime_stage_attempt = sa.Table(
    "acquisition_runtime_stage_attempt",
    METADATA,
    sa.Column(
        "cycle_ref",
        sa.String(64),
        sa.ForeignKey("acquisition_runtime_cycle.cycle_ref", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("stage", sa.String(32), primary_key=True),
    sa.Column("attempt_count", sa.Integer, primary_key=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("reserved_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("observed_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("proposal", sa.JSON),
    sa.Column("retry_at", sa.DateTime(timezone=True)),
    sa.Column("replay_same_attempt", sa.Boolean, nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "stage IN ('SIGNAL_SEED', 'SUPPLIER_DISCOVERY', 'CONTACT_DISCOVERY', "
        "'COMPANY_RESEARCH', 'DECISION', 'PERSONALIZATION', 'COMPLIANCE', "
        "'CAMPAIGN', 'PROVIDER_HANDOFF', 'RESPONSE', "
        "'ATTRIBUTION_CONVERSION')",
        name="ck_acquisition_runtime_attempt_stage",
    ),
    sa.CheckConstraint(
        "status IN ('RUNNING', 'WAITING', 'SUCCEEDED', 'BLOCKED', 'FAILED', "
        "'SUPPRESSED', 'CANCELLED')",
        name="ck_acquisition_runtime_attempt_status",
    ),
    sa.CheckConstraint(
        "attempt_count >= 1",
        name="ck_acquisition_runtime_attempt_count",
    ),
    sa.CheckConstraint(
        "reserved_cost >= 0 AND observed_cost >= 0",
        name="ck_acquisition_runtime_attempt_cost",
    ),
    sa.CheckConstraint(
        "(status = 'RUNNING' AND completed_at IS NULL) OR "
        "(status <> 'RUNNING' AND completed_at IS NOT NULL)",
        name="ck_acquisition_runtime_attempt_lifecycle",
    ),
    sa.CheckConstraint(
        "retry_at IS NULL OR status = 'WAITING'",
        name="ck_acquisition_runtime_attempt_retry",
    ),
    sa.CheckConstraint(
        "replay_same_attempt IS FALSE OR "
        "(status = 'WAITING' AND retry_at IS NOT NULL)",
        name="ck_acquisition_runtime_attempt_replay",
    ),
    sa.Index(
        "ix_acquisition_runtime_attempt_cycle",
        "cycle_ref",
        "completed_at",
    ),
)
