# ADR — Hermes comme Chief of Staff transversal

- Statut : accepté pour V1 SHADOW
- Date : 2026-09-15
- Base : `ef159fa8fcc078f1e85811c76e6cfa2bc60e0eae`

## Contexte

L'intégration Hermes existante produit des plans Acquisition bornés derrière
un processus isolé, un pin vérifié, un schéma strict et zéro outil exécutable.
Kivou dispose déjà des vérités cockpit, Founder, opérations et acquisition ;
les dupliquer dans un agent créerait une seconde autorité.

## Décision

> Hermes devient le Kivou Chief of Staff transversal. Acquisition Supervisor
> reste une spécialisation séparée derrière la même frontière Hermes. Kivou
> demeure propriétaire de la vérité, des métriques, de la mémoire métier, des
> permissions et des décisions critiques.

Le Chief of Staff possède un profil, un contexte et un rapport distincts.
Hermes reçoit seulement des faits structurés et une mémoire approuvée en PR.
Il interprète, cite et recommande ; il n'exécute rien. La sortie est validée
avant une persistance append-only.

## Alternatives rejetées

- Étendre `SupervisorContext` : contrat fourre-tout et couplage des évolutions.
- Dupliquer le bridge : divergence future des protections pin/route/zéro outil.
- Donner des read tools à Hermes : contourne les projections assainies et rend
  le contexte non reproductible.

## Conséquences

La V1 favorise traçabilité et remplacement de fournisseur au prix d'un schéma
plus explicite. Les faits et rapports restent exploitables si Hermes est
remplacé. Toute autonomie future exige une décision et une architecture
séparées.

## Amendement de durcissement — 2026-09-16

La frontière commune ne suffit pas à autoriser un rapport. Le chemin
`report` exige une route dédiée `chief_of_staff`, les quatre paramètres de
modèle/budget et un budget store. Il n'hérite jamais du modèle Hermes générique.
Le chemin Acquisition `plan` reste inchangé.

La disponibilité des modes d'analyse devient un read model déterministe du
contexte : Kivou publie un statut et ses preuves pour chaque capacité. Hermes
ne choisit pas les capacités accessibles. Product Journey et Roadmap/Release
restent explicitement indisponibles en V1 faute de sources déterministes
dédiées ; leur nom décrit une évolution, pas une capacité exécutée.

Un journal `chief_of_staff_attempt` append-only complète le journal financier
des appels modèle. Il sépare succès fournisseur, rejet de structure, rejet
sémantique et publication, sans conserver de prompt, réponse brute ou texte
généré. Le coût réel reste celui du journal modèle, y compris lorsqu'une
réponse facturée est rejetée.
