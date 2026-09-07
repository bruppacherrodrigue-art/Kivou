# Descriptions des produits Stripe

Statut : PREPARATION UNIQUEMENT. Rodrigue doit valider ces textes et effectuer
lui-meme leur mise a jour dans le Dashboard Stripe. Aucun produit Stripe n'a
ete modifie par ce travail.

| Formule | Description proposee |
| --- | --- |
| Essentiel (`essential`) | Signaux de marchés attribués et informations sur les titulaires correspondant à votre profil cible. |
| Pro (`pro`) | Suivi des signaux de marchés attribués et des titulaires correspondant à vos profils cibles. |
| Scale (`scale`), uniquement si toujours actif | Suivi étendu des signaux de marchés attribués et des titulaires correspondant à vos profils cibles. |

Scale figure encore parmi les formules achetables dans
`src/signals/billing/catalogue.py`. Son statut actuel dans Stripe n'a pas ete
consulte : Rodrigue doit confirmer qu'il est toujours actif avant d'appliquer
sa description. Ne pas reactiver un produit archive.

La preparation porte uniquement sur les descriptions. Les noms de produits,
prix, devises, abonnements et reglages fiscaux restent hors de cette mise a jour.

Le changement de code Checkout ajoute `locale="fr"`. La collecte existante
`tax_id_collection={"enabled": True}` et
`customer_update={"name": "auto", "address": "auto"}` sont conservees ;
`automatic_tax` reste pilote par la configuration existante.
