"""`python -m calandria` -- the only entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env support, so the quickstart is two commands and not three."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calandria",
        description="Live transcription and translation for conferences.",
    )
    parser.add_argument("-c", "--config", default="calandria.yaml",
                        help="configuration file (default: calandria.yaml)")
    parser.add_argument("--port", type=int, help="override server.port")
    parser.add_argument("--backend", choices=["gemini", "fake"],
                        help="override stt.backend; 'fake' needs no API key")
    parser.add_argument("--check", action="store_true",
                        help="validate configuration and credentials, then exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _load_dotenv(Path(".env"))

    from .config import Config

    try:
        cfg = Config.load(args.config if Path(args.config).exists() else None)
    except Exception as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.port:
        cfg.server.port = args.port
    if args.backend:
        cfg.stt.backend = args.backend

    if not cfg.sessions:
        print(
            f"No sessions defined in {args.config}. Add at least one stage, or "
            f"copy calandria.example.yaml to get started.",
            file=sys.stderr,
        )
        return 2

    if args.check:
        return _check(cfg)

    from .api import serve

    serve(cfg)
    return 0


def _check(cfg) -> int:
    """Fail loudly at 8am, not at 9:05 during the keynote."""
    from .glossary import Glossary
    from .orchestrator import make_client

    print(f"provider        : {cfg.provider}")
    print(f"stt backend     : {cfg.stt.backend} ({cfg.stt.model})")
    print(f"translation     : {'on' if cfg.translation.enabled else 'off'} "
          f"({cfg.translation.model})")
    print(f"bus             : {cfg.bus}")
    print(f"sessions        : {len(cfg.sessions)}")
    for s in cfg.sessions:
        langs = ", ".join([s.source_language, *s.targets])
        print(f"  - {s.id:<16} {s.source.type:<7} -> {langs}")

    glossary = Glossary.load(cfg.glossary)
    print(f"glossary        : {len(glossary.stt_vocabulary())} terms")
    for w in glossary.warnings():
        print(f"  warning: {w}")

    if cfg.stt.backend == "fake":
        print("\nOK - running with the fake backend, no credentials needed.")
        return 0
    try:
        client = make_client(cfg)
        models = {m.name.split("/")[-1] for m in client.models.list()}
    except Exception as exc:
        print(f"\nFAILED to reach the API: {exc}", file=sys.stderr)
        return 1

    missing = [m for m in (cfg.stt.model, cfg.translation.model) if m not in models]
    if cfg.stt.fallback_enabled and cfg.stt.fallback_model not in models:
        missing.append(cfg.stt.fallback_model)
    if missing:
        print(f"\nFAILED - your key cannot reach: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("\nOK - credentials valid and every configured model is reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
