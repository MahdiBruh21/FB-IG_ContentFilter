# Connecteur Social (Facebook / Instagram) → MongoDB

Collecte des **posts** (image + texte) et leurs **commentaires** liés à un sujet
défini (ex. *« le décès du président Jacques Chirac »*) sur Facebook et/ou
Instagram, puis les stocke dans une base **MongoDB**.

Le code est écrit en **Python 3** et vise une qualité professionnelle : typage
statique, structure modulaire, gestion des erreurs, pagination, gestion du débit
et tests unitaires.

> ⚠️ **Note légale / technique importante**
> L'API officielle Meta **n'explose pas de recherche globale de posts publics par
> mot-clé**. L'approche proposée et conforme aux conditions d'utilisation de Meta
> est donc :
>  - **Facebook** : rechercher des **pages** liées au sujet puis collecter leurs posts.
>  - **Instagram** : rechercher des **hashtags** puis les média (images) associés.
>
> L'utilisation d'un scraping non officiel des APIs de Meta est **interdit par
> leurs CGU** et non couvert par ce projet. Renseignez les accès via le
> [Meta for Developers](https://developers.facebook.com/).

## Fonctionnement et limites

- **Échange de jeton automatique** : un *User Access Token* ne peut pas lire les
  posts d'une page. L'extracteur Facebook échange d'office l'user token contre un
  *Page Access Token* (nécessite le scope `pages_read_engagement`). Le jeton page
  est utilisé uniquement pour les posts/commentaires de cette page ; la recherche
  et l'échange réutilisent toujours l'user token.
- **Recherche par sujet limitée** : l'API Facebook ne remonte **que les pages
  explicitement partagées/accessible** par l'application. Une recherche de type
  « décès de Jacques Chirac » renvoie donc généralement 0 page. La collecte
  privilie donc la page configurée (`FACEBOOK_PAGE_ID`) et ajoute best-effort les
  pages issues de la recherche, en ignorant gracieusement celles auxquels le jeton
  n'a pas accès.
- **Instagram** : requiert un *Instagram Business Account* relié à une Page Facebook,
  l'application doit avoir le scope `instagram_basic`, et l'identifiant doit être un
  *Business Account ID* (et non un *User ID*). L'extracteur résolve automatiquement
  le vrai *Business Account ID* depuis la Page Facebook reliée (`instagram_business_account`)
  si le ID configuré n'est pas accessible — mais cela ne fonctionne **qu'une fois le
  compte relié et le scope `instagram_basic` ajouté dans le dashboard Meta.

## Architecture

```
main.py                     Entrée CLI
config.py                   Chargement de la configuration (.env / environnements)
exceptions.py               Hiérarchie d'exceptions dédiées
logging_config.py           Logging centralisé
social/
  client.py                 Client HTTP Graph API (auth, retry, pagination, débit)
  schemas.py                Modèles normalisés Post / Comment
  extractor.py              Exacteurs Facebook et Instagram (normalisation)
  collector.py              Orchestration recherche → posts → commentaires → Mongo
storage/
  mongo_store.py            Stockage MongoDB (upsert, index, déduplication)
tests/                      Tests unitaires (dépendances standard)
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
# puis renseignez .env (jeton API, identifiants, URI MongoDB)
```

Champs obligatoires : `MONGO_URI`, `META_ACCESS_TOKEN`, et selon la plateforme
`FACEBOOK_PAGE_ID` (Facebook) ou `INSTAGRAM_BUSINESS_ACCOUNT_ID` (Instagram).

## Utilisation

```bash
# Facebook : recherche par pages liées au sujet
python3 main.py --subject "Décès de Jacques Chirac" --platform facebook --limit 50

# Instagram : recherche par hashtags liés au sujet
python3 main.py --subject "Jacques Chirac" --platform instagram
```

Les documents sont insérés dans les collections `posts` et `comments` de la base
`MONGO_DB_NAME` (défaut : `social_media`). La clé unique `(platform, external_id)`
rend la collecte **idempotente** : une relance n'insère pas de doublons.

## Structure des données

**posts** : `external_id`, `platform`, `caption`, `image_urls[]`, `permalink`,
`timestamp`, `author_id`, `author_name`.

**comments** : `_id`, `post_id`, `author_id`, `author_name`, `text`,
`created_at`, `permalink`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Les tests couvrent la normalisation des données, le parsing de configuration et la
logique de déduplication du stockage, **sans** MongoDB ni accès réseau.
