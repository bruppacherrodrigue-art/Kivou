"""Connecteurs vers les portails de marchés publics.

Un connecteur traduit le vocabulaire d'un portail VERS le modèle canonique. La
dépendance est à sens unique : `signals.connectors.*` importe `signals.domain`,
jamais l'inverse. Le domaine ignore qu'eForms, TED ou SIMAP existent.
"""
