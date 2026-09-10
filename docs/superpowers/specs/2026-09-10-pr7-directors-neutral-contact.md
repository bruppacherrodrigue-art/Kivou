# PR7 — dirigeants, contact neutre et formulaires

L'API Recherche d'entreprises est appelée avec `minimal=true` et
`include=dirigeants`. Le registre reste la seule source du nom et de la fonction.
Sont conservés les gérants, cogérants, présidents, présidents du conseil,
directeurs généraux, directeurs généraux délégués, associés gérants et personnes
physiques dirigeantes. Les commissaires aux comptes et représentants sans pouvoir
opérationnel sont exclus. Les dirigeants personnes morales restent dans l'annuaire,
mais ne servent pas de prénom dans le mail.

Une adresse professionnelle publiée et vérifiée MX suffit. Sans dirigeant personne
physique, le message commence par « Bonjour, » et nomme l'entreprise. L'extraction
suit l'ordre `mailto:`, adresse présente dans le texte, puis modèle uniquement si
nécessaire. Une page sans adresse mais avec formulaire sur un domaine d'entreprise
valide est mémorisée dans `supplier_directory` comme canal formulaire, sans devenir
une cible de cold mail. Les données gardent la fraîcheur de 90 jours et la
suppression efface les données personnelles et les retire des campagnes.

