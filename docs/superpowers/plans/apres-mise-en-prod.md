# Chantiers DCE après mise en production

Ces évolutions sont volontairement différées jusqu'après la mise en production
du parcours client. Elles ne doivent pas retarder PR5, PR5b, PR6, la recette ou
PR7.

## Motifs d'échec documentaires fermés

Ajouter un `DocumentFailureReason` fermé, distinct du détail libre, et le rendre
obligatoire pour tout résultat autre que `available`. La taxonomie couvrira au
minimum : consultation clôturée, absence de DCE, page non reconnue, erreur HTTP,
erreur réseau, authentification, CAPTCHA, robots.txt, restriction CGU, contenu
invalide, limite de taille, format non pris en charge, identité manquante, chemin
de portail modifié et circuit d'hôte ouvert. Le motif sera propagé de chaque
adaptateur à `FetchResult`, persisté dans `procedure_documents` et protégé par
une contrainte SQL. Une migration dédiée effectuera un backfill déterministe,
puis les 80 URL PLACE historiques sans motif seront rejouées afin de mesurer une
ventilation sans catégorie « autre/non renseigné ».

La détection ATEXO restera fondée sur une empreinte HTML, jamais sur une liste de
domaines. Les fixtures et tests couvriront explicitement
`marchespublics596280.fr`, `alsacemarchespublics.eu`, `marchespublics.ain.fr` et
`mpe.mairie-marseille.fr`, jusqu'au déclenchement du parcours de téléchargement.

## Archives DCE hors PostgreSQL

Écrire atomiquement les archives sous
`/var/lib/kivou/dce/<procedure>/<empreinte>.<extension>` avec propriétaire
`kivou`, permissions minimales et vérification SHA-256. PostgreSQL conservera
les blocs de texte, métadonnées, taille, empreinte et chemin relatif, mais aucun
blob. La lecture de classification et la purge résoudront ce chemin dans une
racine configurée et protégée contre toute traversée de répertoire.

Une migration dédiée exportera chaque `archive_content` existant vers le disque,
validera taille et empreinte, enregistrera le chemin, puis supprimera la colonne
binaire seulement après succès complet. Elle sera reprise sans doublon après
interruption. Les archives seront sauvegardées par une commande restic séparée
du dump PostgreSQL, avec restauration testée séparément. La répétition Alembic
sur copie jetable devra prouver que le dump SQL source ne transporte déjà plus
les binaires ; le répertoire d'archives ne sera jamais recopié dans la base de
répétition.
