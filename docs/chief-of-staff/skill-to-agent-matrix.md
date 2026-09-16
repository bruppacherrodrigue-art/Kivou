# Évolution des skills vers des agents

La V1 utilise un seul Chief of Staff. Un mode d'analyse ne devient un agent que
si une boucle indépendante, un état durable propre, un volume/concurrence
significatif, des permissions propres, une isolation de panne nécessaire, un
benchmark supérieur, un KPI propre et un gain économique démontré sont tous
documentés.

| Candidat | Skills initiaux | Gates manquants en V1 | Décision V1 |
|---|---|---|---|
| Acquisition Agent | Acquisition Review | permissions et état existent partiellement, benchmark/KPI/gain à prouver | reste spécialisation Supervisor |
| Operations and Data Agent | Operations Review, Data Health Review | boucle, permissions, benchmark et économie à démontrer | reste skill |
| Product and Customer Agent | Product Journey Review | état durable, isolation, benchmark et KPI à définir | reste skill |

Business Review, Strategic Advisor, Pricing Analyst, Roadmap Controller et
Founder Briefing restent des skills du Chief of Staff. Aucun processus autonome
n'est créé par cette PR.

Disponibilité V1 : Business, Data Health, Operations et Acquisition sont
évaluables uniquement lorsque leur contrat source fournit une preuve connue ou
périmée ; Strategic Synthesis exige les quatre. Product Journey et
Roadmap/Release sont enregistrés comme candidats mais `UNAVAILABLE`, faute de
read models et faits déterministes dédiés. Une capacité indisponible ne peut
être citée que comme limite ou inconnue, jamais comme analyse réalisée.
