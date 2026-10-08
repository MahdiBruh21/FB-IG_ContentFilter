"""Point d'entrée CLI du connecteur Social.

Exemple :

    python main.py --subject "Décès de Jacques Chirac" --platform facebook --limit 50
    python main.py --subject "Jacques Chirac"        --platform instagram
"""
from __future__ import annotations

import argparse
import os
import sys

from config import Settings
from exceptions import SocialCollectorError
from logging_config import configure_logging
from social.collector import Collector


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collecte des posts (image/texte) et commentaires d'un sujet sur Facebook/Instagram.",
    )
    parser.add_argument("--subject", required=True, help="Sujet de recherche (ex: décès de Jacques Chirac).")
    parser.add_argument(
        "--platform",
        required=True,
        choices=["facebook", "instagram"],
        help="Plateforme source.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limite de posts (écrase la config).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()

    try:
        # Settings est immuable (frozen) : l'écrasement de limite passe par
        # la variable d'environnement AVANT la construction.
        if args.limit:
            os.environ["SEARCH_LIMIT"] = str(args.limit)
        settings = Settings.from_env()
        collector = Collector(settings)
        summary = collector.run(args.subject, args.platform)
    except SocialCollectorError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("Interruption utilisateur.", file=sys.stderr)
        return 130

    print("Résultats :", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
