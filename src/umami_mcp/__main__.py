"""Entry point: ``python -m umami_mcp`` or the ``umami-mcp-server`` console script.

Loads a local ``.env`` (if present) so credentials can live in a file during dev,
then runs the MCP server over stdio.
"""

from __future__ import annotations

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    # Imported here so a missing optional dependency or bad import surfaces at run
    # time with a clear traceback rather than at console-script generation.
    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
