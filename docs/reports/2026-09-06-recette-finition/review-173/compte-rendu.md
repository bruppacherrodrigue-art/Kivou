# #173 : revue du 6 septembre 2026
1. Version applicative poussee et active sur staging : `18e37b8e454150a2e3b0670b9f8f7d150d885b41`.
2. Trois assertions alignees : France, date courte et seuil mobile de 899 px ; aucun changement du format de date.
3. `ScreenHeader`, `ScreenSegments` et `SummaryRow` extraits des ecrans existants et reutilises par Reglages ; aucune primitive `Settings*` ajoutee.
4. Entreprises : liste interactive a deux colonnes, panneau de 520 px sans voile, changement de selection verifie ([desktop](after/essentiel-1440-companies-switched.png), [mobile](after/essentiel-390-companies.png)).
5. Signaux : cartes ouvertes et verrouillees a trois lignes, objet sur deux lignes maximum, aucun tableau a 390 px ([capture](after/decouverte-390-signals.png)).
6. En-tete mobile : meme fonction `sharedZoneLabels`, France sans code FR ([Decouverte](after/decouverte-390-header.png), [Essentiel](after/essentiel-390-header.png)).
7. Reglages : composants partages, champs absents omis et titres sans-serif ([desktop](after/essentiel-1440-settings.png), [mobile](after/essentiel-390-settings.png)).
8. Avant correction sur staging : 12 echecs et 2 succes ; [resultats et causes](before/results.json), captures conservees dans `before/`.
9. Apres correction sur staging : 14/14 controles Playwright reussis, Decouverte et Essentiel, 1440 et 390 px ; [resultats](after/results.json).
10. Drawer ouvert sur les deux comptes et les deux formats ; exemples [desktop](after/essentiel-1440-drawer.png) et [mobile](after/decouverte-390-drawer.png).
11. Validation locale : TypeScript reussi et [674/674 tests frontend reussis](vitest-final.log), sans migration locale ni nouvelle variable d'environnement.
12. Script serveur : echec exact `api_readiness=timeout unit=kivou-api.service attempts=5` apres bascule ; [sortie integrale](deploy-18e37b8.log) et [commandes/instructions citees](commandes.md).
13. Diagnostic ulterieur du meme helper : `api_readiness=ready unit=kivou-api.service port=8000 attempt=1` ; cela n'annule pas l'echec du script.
14. Fusion bloquee : [CI applicative](https://github.com/bruppacherrodrigue-art/Kivou/actions/runs/34044884141) rouge, 12 tests visuels et deux assertions backend (Secteur Essentiel, repli CPV) ; aucune fusion effectuee.
