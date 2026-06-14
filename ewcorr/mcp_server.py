"""EWCORR MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from ewcorr.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-ewcorr[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-ewcorr[mcp]'")
        return 1
    app = FastMCP("ewcorr")

    @app.tool()
    def ewcorr_scan(target: str) -> str:
        """Correlate EW/ELINT event logs by time/frequency/bearing.

        Clusters emitters and returns JSON findings.
        """
        return to_json(scan(target))

    app.run()
    return 0
