"""stdio MCP server entry. `python -m cogniwork.tools.mcp_server --provider gcal`."""

from __future__ import annotations

import json
import os
import sys

from cogniwork.tools.catalog import load_catalog
from cogniwork.tools.http import HttpTransport, StubTransport
from cogniwork.tools.mcp import handle_rpc


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    provider = "gcal"
    if "--provider" in args:
        provider = args[args.index("--provider") + 1]
    token = os.environ.get("COGNIWORK_MCP_TOKEN") or ""
    catalog = load_catalog()
    transport: HttpTransport
    if os.environ.get("COGNIWORK_OAUTH_STUB") == "true":
        transport = StubTransport()
    else:
        transport = HttpTransport()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        response = handle_rpc(
            request,
            provider=provider,
            token=token,
            catalog=catalog,
            transport=transport,
        )
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
