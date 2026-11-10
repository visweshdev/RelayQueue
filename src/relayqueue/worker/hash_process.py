"""Private CPU subprocess; killed on parent death in Linux Compose containers."""

import ctypes
import hashlib
import json
import os
import signal
import sys
import threading


def main() -> None:
    parent, deadline = int(sys.argv[1]), int(sys.argv[2])
    if sys.platform == "linux":
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Could not enable parent-death signal")
        if os.getppid() != parent:
            sys.exit(1)
    watchdog = threading.Timer(deadline + 1, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        payload = json.load(sys.stdin)
        value = str(payload["buffer"]).encode()
        iterations = int(payload["iterations"])
        for _ in range(iterations):
            value = hashlib.sha256(value).digest()
        print(json.dumps({"digest": value.hex(), "iterations": iterations}))
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    main()
