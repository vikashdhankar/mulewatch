"""python -m watcher <command>   (run from backend/)

  run                   poll approved channels until stopped (systemd: deploy/systemd/mulewatch-watcher.service)
  login                 log the watcher's own Telegram session in (once, in a terminal)
  replay FILE           replay collected posts (research/store/raw/telegram.jsonl) through the pipeline
                        --speed 50x  --push (also send Telegram alerts)  --limit N
  retrain               retrain the fallback TF-IDF + LR model (after new annotations or decisions)
  health                print the watcher's health as JSON
  export-feedback       write officers' decisions to research/store/annotations/watcher/ as labelled data
"""
import argparse
import asyncio
import json
import os
import sys

from . import research  # noqa: F401  (sys.path + research/.env first)


def _salt() -> str:
    salt = os.environ.get("WATCHER_HASH_SALT") or os.environ.get("RESEARCH_HASH_SALT", "")
    if len(salt) < 16:
        raise SystemExit("set RESEARCH_HASH_SALT (or WATCHER_HASH_SALT) in research/.env: "
                         "python -c \"import secrets; print(secrets.token_hex(32))\"")
    return salt


def build(cfg: dict, retrain: bool = False):
    from app.db import init_db
    from pii.redact import Redactor

    from .classifier import load_model, make_llm
    from .process import Processor
    init_db()
    red = Redactor(_salt())
    model = load_model(cfg, red, retrain=retrain)
    import logging
    logging.getLogger("watcher").info("classifier: %s", model.name)
    return Processor(cfg, red, model, make_llm(cfg))


def main(argv=None):
    from . import config, logs
    ap = argparse.ArgumentParser(prog="python -m watcher", description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None, help="watcher.yaml to use (default: WATCHER_CONFIG or the bundled one)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true", help="one polling cycle, then exit")
    sub.add_parser("login")
    rp = sub.add_parser("replay")
    rp.add_argument("file")
    rp.add_argument("--speed", default="50x")
    rp.add_argument("--push", action="store_true", help="also send HIGH alerts to the linked Telegram chat")
    rp.add_argument("--limit", type=int, default=None)
    rp.add_argument("--window-hours", type=float, default=None,
                    help="replay only the last N hours in real time; older posts become history (no alerts)")
    sub.add_parser("retrain")
    sub.add_parser("health")
    ex = sub.add_parser("export-feedback")
    ex.add_argument("--out", default=None, help="default research/store/annotations/watcher")
    args = ap.parse_args(argv)
    logs.setup(args.verbose)
    cfg = config.load(args.config)

    if args.cmd == "login":
        from .telegram import connect

        async def go():
            client = await connect(cfg, interactive=True)
            me = await client.get_me()
            print(f"logged in as user id {me.id}; session kept for the watcher")
            await client.disconnect()
        asyncio.run(go())
    elif args.cmd == "run":
        from .telegram import Poller, connect
        proc = build(cfg)

        async def go():
            client = await connect(cfg)
            try:
                await Poller(cfg, proc, client).run(once=args.once)
            finally:
                await client.disconnect()
        try:
            asyncio.run(go())
        except KeyboardInterrupt:
            pass
    elif args.cmd == "replay":
        from .replay import parse_speed, replay
        proc = build(cfg)
        out = replay(args.file, proc, parse_speed(args.speed), cfg["replay"]["max_gap_s"], args.push, args.limit,
                     window_hours=args.window_hours)
        print(json.dumps(out))
    elif args.cmd == "retrain":
        m = build(cfg, retrain=True).model
        print(m.name)
    elif args.cmd == "health":
        from app import watcher_api
        from app.db import SessionLocal, init_db
        init_db()
        with SessionLocal() as s:
            print(json.dumps(watcher_api.health_report(s), indent=1, default=str))
    elif args.cmd == "export-feedback":
        from app import watcher_api
        from app.db import SessionLocal, init_db
        init_db()
        with SessionLocal() as s:
            print(json.dumps(watcher_api.export_feedback(s, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
