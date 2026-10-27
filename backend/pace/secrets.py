"""Encrypting the Time Doctor passwords people give Pace.

Each person's password is kept as a Fernet token (AES with an HMAC) in the
database. The key is `PACE_SECRET_KEY` if set, or else a key file beside the
database, made on first use with mode 0600.

What that buys: the nightly backup copies the database alone (VACUUM INTO),
not the key file, so a backup that leaks doesn't leak anyone's password.
What it doesn't: someone who can read the server's state directory can read
both. The real protection there is the server itself.

Losing the key (a restore onto a fresh box) loses nothing else: everyone
types their Time Doctor password into settings once more.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class SecretError(Exception):
    pass


def _key_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings().db_path)), "secret.key")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("PACE_SECRET_KEY", "").encode()
    if not key:
        path = _key_path()
        if not os.path.exists(path):
            # O_EXCL: if the web app and the worker race to make it, one wins
            # and the other reads the winner's key.
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            except FileExistsError:
                pass
        with open(path, "rb") as f:
            key = f.read().strip()
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise SecretError("A stored Time Doctor password can't be read with this server's key; enter it again.")


def reset_cache() -> None:
    _fernet.cache_clear()
