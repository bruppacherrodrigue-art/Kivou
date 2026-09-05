# PR5b — JSON replay diagnostic fixes

**Goal:** rendre le replay diagnostiquable, tolérant aux enveloppes fournisseur et strict sur les faits affichés avant une nouvelle mesure de 50 couples.

**Design:** la ligne `for_you_sentence` conserve uniquement la réponse brute des rejets, tronquée à 2 000 caractères, avec une échéance à 30 jours. Le worker extrait le premier objet JSON exploitable, assemble lui-même tous les faits, puis purge les réponses expirées à chaque passage. OpenRouter demande `json_object`. Le titulaire est omis lorsqu’aucun nom contenant des lettres n’est disponible ; le lieu est limité à la ville ou au département.

## Lots TDD

- [ ] Tests rouges : extraction JSON depuis réponse pure, fences et texte périphérique ; absence des deux clés reste `invalid_shape`.
- [ ] Tests rouges : nom d’entreprise, identifiant seul, lieu ville/département/pays et gabarit sans titulaire.
- [ ] Tests rouges : journal brut rejeté tronqué, absence sur succès, purge à J+30.
- [ ] Implémenter parsing, assemblage, stockage et migration Alembic en mode batch SQLite.
- [ ] Vérifier les tests ciblés, Ruff et la migration.
- [ ] Déployer staging par `kivou-deploy.sh`.
- [ ] Préparer exactement 17/17/16 nouvelles lignes et vérifier la répartition avant tout appel.
- [ ] Lancer une fois, puis publier taux, motifs, cinq bruts rejetés, doublons de conséquence et vingt phrases.
