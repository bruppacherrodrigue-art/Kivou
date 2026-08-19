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
    sa.CheckConstraint(
        "stream_version >= 1", name="ck_acquisition_opportunity_stream_version"
    ),
    sa.CheckConstraint(
        "retry_count >= 0", name="ck_acquisition_opportunity_retry_count"
    ),
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
    sa.CheckConstraint(
        "stream_sequence >= 1", name="ck_acquisition_event_stream_sequence"
    ),
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
        sa.ForeignKey(
            "acquisition_opportunity.acquisition_opportunity_id", ondelete="RESTRICT"
        ),
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
    sa.Column("approval_ids", sa.JSON, nullable=False),
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
