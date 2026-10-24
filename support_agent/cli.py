"""``support-agent``: terminal chat, database reset and OpenAPI export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from support_agent.config import Settings


def cmd_chat(args: argparse.Namespace) -> int:
    from support_agent.service import SupportService

    settings = Settings()
    if args.memory:
        settings = settings.model_copy(update={"database_path": ":memory:"})
    svc = SupportService(settings)
    new = svc.start_session(args.customer)
    print(f"Signed in as {new.customer['name']} ({args.customer}). Ctrl-D to quit.\n")
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        session = svc.repo.get_session(new.session_id)
        result = svc.send(session, text)  # type: ignore[arg-type]
        for step in result.trace:
            if step["type"] == "tool":
                print(
                    f"  · {step['name']}({json.dumps(step['arguments'], ensure_ascii=False)}) "
                    f"-> {step['status']}"
                )
            elif step["type"] == "guardrail":
                print(f"  ! guardrail {step['name']}")
        print(f"agent> {result.reply}  [{result.state}]\n")
    return 0


def cmd_reset(_: argparse.Namespace) -> int:
    from support_agent.service import SupportService

    settings = Settings()
    path = Path(settings.database_path)
    if path.exists():
        path.unlink()
    SupportService(settings)
    print(f"recreated and seeded {path}")
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    from support_agent.api.main import create_app

    settings = Settings(_env_file=None, database_path=":memory:")
    spec = create_app(settings).openapi()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(spec['paths'])} paths)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="support-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    chat = sub.add_parser("chat", help="chat with the agent in the terminal")
    chat.add_argument("--customer", default="C001", help="seeded customer id (C001-C004)")
    chat.add_argument("--memory", action="store_true", help="use a throwaway in-memory database")
    chat.set_defaults(func=cmd_chat)
    reset = sub.add_parser("reset-db", help="delete and re-seed the SQLite database")
    reset.set_defaults(func=cmd_reset)
    oa = sub.add_parser("openapi", help="export the OpenAPI document")
    oa.add_argument("output", nargs="?", default="openapi.json")
    oa.set_defaults(func=cmd_openapi)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
