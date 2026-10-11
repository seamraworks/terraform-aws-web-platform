import argparse
import json
import sys
from .contract import ModerationRequest
from .providers import create_provider


def main():
    parser = argparse.ArgumentParser(description="Classify JSON from stdin; never deletes content")
    parser.add_argument("--config", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        with open(args.config, encoding="utf-8") as source:
            config = json.load(source)
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError("Request exceeds size limit")
        request = ModerationRequest.from_dict(json.loads(raw))
        result = create_provider(config, args.database).classify(request)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    except Exception as exc:
        # Keys, content and remote response bodies must never appear in failures.
        print(json.dumps({"error": type(exc).__name__, "retain_content": True}), file=sys.stderr)
        raise SystemExit(1)
