"""Private scoped broker credential reader, shared without host runner imports."""

import os
import stat


def read_token(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Broker credential must be a private owned file")
        token = source.read(257).strip()
    if (
        not token.isascii()
        or len(token) < 32
        or len(token) > 256
        or any(c.isspace() for c in token)
    ):
        raise ValueError("Invalid broker credential")
    return token
