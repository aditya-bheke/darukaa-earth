"""Command-line interface.

    python -m darukaa.cli                          # interactive chat
    python -m darukaa.cli --json site.json         # one-shot structured input
    python -m darukaa.cli --json site.json --raw   # print the structured JSON response
"""

import argparse
import json
import sys

from darukaa.engine import Engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Darukaa.Earth AI environmental scientist")
    parser.add_argument("--json", help="path to a JSON file with site data")
    parser.add_argument("--message", default="", help="optional text to send with the JSON")
    parser.add_argument("--session", help="resume an existing session id")
    parser.add_argument("--raw", action="store_true", help="print structured JSON instead of markdown")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    engine = Engine(args.session)
    if args.json:
        with open(args.json, encoding="utf-8") as fh:
            data = json.load(fh)
        resp = engine.handle(args.message, data)
        print(resp.model_dump_json(indent=2) if args.raw else resp.message)
        return

    print(f"Session {engine.session_id}. Describe your land (Ctrl+C to quit).")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text:
            resp = engine.handle(text)
            print("\n" + (resp.model_dump_json(indent=2) if args.raw else resp.message))


if __name__ == "__main__":
    main()
