"""``python -m xpm.replay`` — the replay container's entrypoint.

A shim over :mod:`xpm.replay.runner`, which holds the connect/serve/reconnect
logic so that it is coverage-measured rather than omit-listed (R6, R21).
"""

from __future__ import annotations

from xpm.replay.runner import main

if __name__ == "__main__":
    main()
