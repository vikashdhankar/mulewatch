"""Logging for the watcher: a filter masks anything that looks like a phone number, UPI ID, account, card,
e-mail or link before a line is written, as a safety net under the rule that log calls never include post text
or identifier values."""
import logging

_RX = None


def _masker():
    from pii.redact import Redactor
    red = Redactor(b"log-filter-salt-never-used-for-hashes")
    return lambda s: red.redact(s)[0]


class RedactFilter(logging.Filter):
    def filter(self, record):
        global _RX
        if _RX is None:
            _RX = _masker()
        msg = record.getMessage()
        masked = _RX(msg)
        if masked != msg:
            record.msg, record.args = masked, ()
        return True


def setup(verbose: bool = False):
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for noisy in ("telethon", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
