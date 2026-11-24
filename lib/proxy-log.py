"""Timestamp each physical line of the proxy's combined stdout/stderr."""

import sys
from datetime import datetime

port = sys.argv[1]
for line in sys.stdin.buffer:
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    message = line.decode("utf-8", errors="replace").rstrip("\r\n")
    print(f"{timestamp} [mitmdump port={port}] {message}", flush=True)
