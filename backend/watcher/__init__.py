"""Real-time watcher for approved public Telegram channels, feeding the MuleWatch command center.

    cd backend && python -m watcher run                  # poll approved channels (needs `login` once)
    cd backend && python -m watcher replay ../research/store/raw/telegram.jsonl --speed 50x

See backend/watcher/README.md."""
