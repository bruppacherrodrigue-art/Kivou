# PR7 — chaîne de contact PME

Le SIREN reste l’identité fournisseur. Pour chaque société SIRENE, Kivou cherche d’abord un
domaine : champ public de Recherche d’entreprises s’il existe, sinon un unique appel Serper
`{raison sociale nettoyée} {ville}`. Un résultat Serper n’est accepté que si son titre ou son URL
contient tous les mots significatifs du nom et si son domaine n’est pas un annuaire. Le binding
SIREN conserve le domaine, sa source, la méthode Apollo et les dates ; les journaux ne contiennent
aucune clé ni réponse brute.

Apollo résout d’abord l’organisation par domaine exact, puis seulement par nom normalisé et ville.
La recherche de personnes reste bornée aux titres de décideurs et aux adresses `verified`. Si elle
ne produit rien, Kivou charge au plus deux pages du même domaine (accueil et contact), avec taille,
temps et réseau bornés. Un modèle derrière `contact_discovery/providers.py` retourne un JSON strict.
Le code accepte uniquement un dirigeant présent dans les données publiques et une adresse
littéralement publiée dans les pages. L’adresse passe ensuite un contrôle MX puis SMTP `RCPT TO`,
sans commande `DATA` et donc sans envoi. Une boîte générique n’est jamais retenue sans dirigeant
nommé.

Le cycle SHADOW conserve son plafond d’une cible. Une commande de mesure séparée rejoue le même
profil SIRENE sur tout le stock disponible et produit les compteurs par famille sans activer le timer.
La famille `subcontracted_structural_work` couvre `43.99C`; `reinforcement_steel` couvre `24.10Z` et
`25.11Z`. Tous les fournisseurs réseau ont des faux déterministes pour staging et les tests.

