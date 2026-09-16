# Chief of Staff — sécurité et données exclues

Le contexte Hermes contient seulement mémoire approuvée, faits structurés,
gates/incidents assainis et métadonnées de version. Tout contenu reçu est
marqué `UNTRUSTED_DATA` et ne peut être interprété comme instruction.

Sont explicitement exclus : adresse email, corps d'email, nom ou note de
prospect, texte client brut, texte marché/fournisseur/document brut, secret,
clé, token, cookie, URL signée, prompt brut, réponse fournisseur brute,
identifiant administrateur, session/engine SQL, chemin libre, shell, MCP,
client Apollo/Instantly/Stripe et ancien rapport comme instruction.

Les seules écritures V1 sont le journal de réservation/finalisation modèle, le
journal de tentative assaini et le rapport validé append-only. Le journal de
tentative ne contient que des identifiants, périodes, versions, codes fermés et
coûts issus du journal modèle : aucun prompt, réponse fournisseur, texte
généré, email, PII ou secret. Il n'existe aucune route de génération ou
d'action, aucun outil Hermes, et aucune mutation de policy/gate/pricing/score.
