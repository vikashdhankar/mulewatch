"""Old entry point for the SP account, kept so `../.venv/bin/python create_sp_admin.py` still works.

The code lives in app/sp_admin.py; prefer `./run.sh add-sp` (see `./run.sh add-sp --help`).
"""
import sys

from app.sp_admin import main

if __name__ == "__main__":
    sys.exit(main())
