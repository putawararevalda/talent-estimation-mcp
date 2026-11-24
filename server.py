"""Talent Estimation & Sizing Model Context Protocol (MCP) Server.

Wraps the AIX (Talent Estimation Agent) remote HTTP API with dual-method
FTE sizing (Use Case Points and Bottom-Up), capability matching, and AI augmentation.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from aix_client import AIXClient
from cache import run_cache

load_dotenv()

# Initialize FastMCP Server
mcp = FastMCP("talent-estimation-mcp")
# Allow public cloud hostnames (disable local-only DNS rebinding filter)
mcp.settings.transport_security.enable_dns_rebinding_protection = False
client = AIXClient()


@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """Check the health and reachability of the remote AIX engine."""
    try:
        remote_health = await client.check_health()
        return {
            "status": "healthy",
            "mcp_server": "running",
            "remote_aix": remote_health,
            "base_url": client.base_url,
        }
    except Exception as e:
        return {
            "status": "degraded",
            "mcp_server": "running",
            "remote_aix_error": str(e),
            "base_url": client.base_url,
        }


@mcp.tool()
async def get_capability_catalog(team: Optional[str] = None) -> Dict[str, Any]:
    """Fetch the capability catalog containing role scopes, capability areas, and competency rules.

    Args:
        team: Optional filter by team ('data', 'design', or None for all).
    """
    try:
        catalog = await client.get_default_catalog()
        roles_data = catalog.get("roles", {})
        if team:
            roles_data = {k: v for k, v in roles_data.items() if v.get("team") == team}

        summary = {}
        for code, info in roles_data.items():
            summary[code] = {
                "name": info.get("name"),
                "team": info.get("team"),
                "summary": info.get("summary"),
                "capability_areas": list(info.get("capability_areas", {}).keys()),
                "in_scope": info.get("in_scope"),
                "primary_keywords": info.get("primary_keywords"),
            }
        return {
            "version": catalog.get("version"),
            "teams": catalog.get("teams"),
            "roles": summary,
        }
    except Exception as e:
        return {"error": f"Failed to fetch catalog: {str(e)}"}


@mcp.tool()
async def estimate_wbs(
    project_name: str = "Project Estimation",
    tasks: Optional[List[Dict[str, Any]]] = None,
    tasks_csv: Optional[str] = None,
    scope: str = "all",
    hours_per_day: float = 8.0,
    days_per_month: float = 20.0,
    phm: float = 15.0,
    support_factor: float = 0.25,
    tolerance: float = 0.15,
    requested_fte: Optional[Dict[str, float]] = None,
    existing_fte: Optional[Dict[str, float]] = None,
    use_demo: bool = False,
) -> Dict[str, Any]:
    """Execute talent and workload estimation on a Work Breakdown Structure (WBS).

    Calculates FTE using dual methodologies: Use Case Points (UCP) and Bottom-Up (BU),
    identifies gaps and overlaps, and calculates potential AI augmentation hours saved.

    Args:
        project_name: Name of the project or initiative.
        tasks: List of task objects with fields: 'name' or 'item', 'description', 'role', 'workdays'.
        tasks_csv: Optional raw CSV string of WBS items.
        scope: Target scope ('data', 'design', or 'all').
        hours_per_day: Work hours per day (default: 8.0).
        days_per_month: Work days per month (default: 20.0).
        phm: Person-hours per month (default: 15.0).
        support_factor: Non-project overhead multiplier (default: 0.25).
        tolerance: Discrepancy tolerance between UCP and BU (default: 0.15 / 15%).
        requested_fte: Map of role codes to requested FTEs, e.g. {"DE": 1.0, "DS": 1.0}.
        existing_fte: Map of role codes to existing headcount, e.g. {"DA": 0.5}.
        use_demo: Set to True to run with built-in standard demo WBS.

    Returns:
        Structured estimation findings, comparison table, message draft, and a `run_id` for refinements.
    """
    try:
        events, run_result = await client.create_run(
            project_name=project_name,
            tasks=tasks,
            tasks_csv_or_text=tasks_csv,
            scope=scope,
            hours_per_day=hours_per_day,
            days_per_month=days_per_month,
            phm=phm,
            support_factor=support_factor,
            tolerance=tolerance,
            requested_fte=requested_fte,
            existing_fte=existing_fte,
            use_demo=use_demo,
        )

        # Store in cache
        run_id = run_cache.store(run_result)

        # Extract high-level summary
        role_summaries = []
        for r in run_result.get("role_inputs", []):
            role_code = r.get("role")
            role_summaries.append({
                "role": role_code,
                "requested_fte": r.get("requested_fte", 0.0),
                "existing_fte": r.get("existing_fte", 0.0),
            })

        augmentation = []
        for a in run_result.get("augmentation", []):
            augmentation.append({
                "role": a.get("role"),
                "baseline_days": a.get("baseline_person_days"),
                "saved_days": round(a.get("saved_person_days", 0.0), 2),
                "saving_share": f"{round(a.get('saving_share', 0.0) * 100, 1)}%",
                "ucp_fte": round(a.get("ucp_fte", 0.0), 2),
                "ucp_fte_assisted": round(a.get("ucp_fte_assisted", 0.0), 2),
                "bu_fte": round(a.get("bu_fte", 0.0), 2),
                "bu_fte_assisted": round(a.get("bu_fte_assisted", 0.0), 2),
            })

        return {
            "run_id": run_id,
            "project": run_result.get("project"),
            "message_draft": run_result.get("message_draft"),
            "role_inputs": role_summaries,
            "augmentation_summary": augmentation,
            "items_count": len(run_result.get("items", [])),
            "findings_count": len(run_result.get("findings", [])),
            "instructions": "Use run_id with 'recalculate_plan' or 'export_validation_excel' for follow-up actions.",
        }
    except Exception as e:
        return {"error": f"Estimation failed: {str(e)}"}


@mcp.tool()
async def recalculate_plan(
    run_id: str,
    hours_per_day: Optional[float] = None,
    days_per_month: Optional[float] = None,
    support_factor: Optional[float] = None,
    tolerance: Optional[float] = None,
    requested_fte: Optional[Dict[str, float]] = None,
    existing_fte: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Deterministically recalculate an existing plan without re-running LLM agents.

    Instant calculation used to test different assumptions, workdays, or headcount allocations.

    Args:
        run_id: The run identifier returned from `estimate_wbs`.
        hours_per_day: Updated hours per day (optional).
        days_per_month: Updated days per month (optional).
        support_factor: Updated overhead factor (optional).
        tolerance: Updated tolerance threshold (optional).
        requested_fte: Updated requested FTEs map by role, e.g. {"DE": 2.0}.
        existing_fte: Updated existing FTEs map by role.
    """
    cached_run = run_cache.get(run_id)
    if not cached_run:
        return {"error": f"Run '{run_id}' not found in cache or expired."}

    # Update parameters if provided
    params = cached_run.get("parameters", {})
    if hours_per_day is not None:
        params["hours_per_day"] = hours_per_day
    if days_per_month is not None:
        params["days_per_month"] = days_per_month
    if support_factor is not None:
        params["support_factor"] = support_factor
    if tolerance is not None:
        params["tolerance"] = tolerance
    cached_run["parameters"] = params

    # Update role inputs if provided
    if requested_fte or existing_fte:
        role_inputs = cached_run.get("role_inputs", [])
        for r in role_inputs:
            code = r.get("role")
            if requested_fte and code in requested_fte:
                r["requested_fte"] = float(requested_fte[code])
            if existing_fte and code in existing_fte:
                r["existing_fte"] = float(existing_fte[code])
        cached_run["role_inputs"] = role_inputs

    try:
        updated_run = await client.recalculate(cached_run)
        run_cache.update(run_id, updated_run)
        return {
            "run_id": run_id,
            "status": "recalculated",
            "message_draft": updated_run.get("message_draft"),
            "parameters": updated_run.get("parameters"),
        }
    except Exception as e:
        return {"error": f"Recalculation failed: {str(e)}"}


@mcp.tool()
async def export_validation_excel(run_id: str, save_path: Optional[str] = None) -> Dict[str, Any]:
    """Export the validation workbook (.xlsx) for an existing estimation run.

    Args:
        run_id: The run identifier returned from `estimate_wbs`.
        save_path: Optional absolute destination path on the host. If omitted, saves to current directory.
    """
    cached_run = run_cache.get(run_id)
    if not cached_run:
        return {"error": f"Run '{run_id}' not found in cache or expired."}

    try:
        excel_bytes = await client.export_excel(cached_run)
        file_path = save_path or f"aix_validation_{run_id}.xlsx"
        with open(file_path, "wb") as f:
            f.write(excel_bytes)
        return {
            "status": "success",
            "run_id": run_id,
            "saved_file": os.path.abspath(file_path),
            "size_bytes": len(excel_bytes),
        }
    except Exception as e:
        return {"error": f"Excel export failed: {str(e)}"}


def build_app():
    """Builds Starlette application supporting both Streamable HTTP (/mcp) and SSE (/sse)."""
    # 1. Base app with Streamable HTTP (/mcp) and session lifecycle manager
    app = mcp.streamable_http_app()

    # 2. Append legacy SSE endpoints (/sse and /messages)
    sse_app = mcp.sse_app()
    for route in sse_app.routes:
        app.routes.append(route)

    # 3. Informational and health probe endpoints
    async def root_handler(request):
        return JSONResponse({
            "service": "talent-estimation-mcp",
            "status": "running",
            "transports": ["Streamable HTTP (/mcp)", "SSE (/sse)"],
            "endpoints": {
                "mcp": "/mcp",
                "sse": "/sse",
                "messages": "/messages",
                "health": "/health",
            },
            "docs": "For Streamable HTTP clients (Agona, etc.), connect to /mcp. For SSE clients, connect to /sse.",
        })

    async def health_handler(request):
        return JSONResponse({"status": "healthy"})

    app.routes.append(Route("/", root_handler, methods=["GET"]))
    app.routes.append(Route("/health", health_handler, methods=["GET"]))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Talent Estimation MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run with stdio transport")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 80)), help="Port for SSE transport")
    args = parser.parse_args()

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        print(f"Starting Talent Estimation MCP Server (SSE) on 0.0.0.0:{args.port}...")
        app = build_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
