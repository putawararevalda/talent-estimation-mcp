"""HTTP client wrapping the remote AIX (Talent Estimation Agent) REST API."""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

DEFAULT_BASE_URL = "https://93id1-aix.labs.playdev.online"
DEFAULT_TIMEOUT = 120.0


class AIXClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        cookie: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or os.getenv("AIX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.cookie = cookie or os.getenv("AIX_SESSION_COOKIE") or ""
        self.llm_api_key = llm_api_key or os.getenv("AIX_LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        self.timeout = timeout

    def _get_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "User-Agent": "Mozilla/5.0 (compatible; AIX-MCP-Client/1.0)",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        key = api_key or self.llm_api_key
        if key:
            headers["x-llm-api-key"] = key
        return headers

    async def check_health(self) -> Dict[str, Any]:
        """Checks remote API health endpoint."""
        url = f"{self.base_url}/api/py/health"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def get_default_catalog(self) -> Dict[str, Any]:
        """Fetches the default capability catalog from AIX."""
        url = f"{self.base_url}/api/py/catalog"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            return resp.json()

    async def create_run(
        self,
        project_name: str = "",
        tasks: Optional[List[Dict[str, Any]]] = None,
        tasks_csv_or_text: Optional[str] = None,
        scope: str = "all",
        hours_per_day: float = 8.0,
        days_per_month: float = 20.0,
        phm: float = 15.0,
        support_factor: float = 0.25,
        tolerance: float = 0.15,
        requested_fte: Optional[Dict[str, float]] = None,
        existing_fte: Optional[Dict[str, float]] = None,
        use_demo: bool = True,
        api_key: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Executes a full estimation run via /api/py/runs.

        Returns (progress_events, final_run_dict).
        """
        url = f"{self.base_url}/api/py/runs"

        # Auto-fallback to demo (rule-based) mode if no API key is configured or no tasks are passed
        active_api_key = api_key or self.llm_api_key
        effective_demo = use_demo
        if not effective_demo and not active_api_key:
            effective_demo = True
        elif not tasks and not tasks_csv_or_text:
            effective_demo = True

        # 1. Build role inputs list
        roles = ["DE", "DA", "DS", "AI", "UXR", "UX", "UI"]
        role_inputs = []
        req_map = requested_fte or {}
        exist_map = existing_fte or {}
        for r in roles:
            role_inputs.append({
                "role": r,
                "requested_fte": float(req_map.get(r, 0.0)),
                "existing_fte": float(exist_map.get(r, 0.0)),
                "reference_fte": None,
            })

        # 2. Build settings payload
        settings_payload: Dict[str, Any] = {
            "project": {
                "name": project_name,
                "start": None,
                "end": None,
                "scope": scope,
                "context": "",
                "reference": "",
            },
            "parameters": {
                "hours_per_day": hours_per_day,
                "days_per_month": days_per_month,
                "phm": phm,
                "support_factor": support_factor,
                "tolerance": tolerance,
                "duration_override_months": None,
                "holidays": [],
                "use_case_weights": {"Simple": 5, "Average": 10, "Complex": 15},
                "actor_weights": {"Simple": 1, "Average": 2, "Complex": 3},
            },
            "role_inputs": role_inputs,
            "ai_enabled": True,
            "ai_tools": [],
            "provider": {
                "provider": "google",
                "model": "gemini-3.8-flash",
                "base_url": None,
                "api_version": None,
                "temperature": 0,
                "mask_pii": True,
                "send_temperature": True,
                "max_tokens": 8192,
                "extra_headers": {},
                "structured_method": "auto",
            },
            "demo": effective_demo,
            "catalog": None,
        }

        # 3. Handle files
        files: Dict[str, Any] = {}
        if not effective_demo:
            csv_content = ""
            if tasks_csv_or_text:
                csv_content = tasks_csv_or_text
            elif tasks:
                csv_lines = ["No,Item,Deskripsi,Role,Durasi (hari),Mulai,Selesai"]
                for i, t in enumerate(tasks, start=1):
                    name = t.get("name", t.get("item", f"Task {i}")).replace(",", ";")
                    desc = t.get("description", t.get("deskripsi", "")).replace(",", ";")
                    role = t.get("role", t.get("role_hint", ""))
                    dur = t.get("workdays", t.get("duration", 5))
                    start = t.get("start", "")
                    end = t.get("end", "")
                    csv_lines.append(f"{i},{name},{desc},{role},{dur},{start},{end}")
                csv_content = "\n".join(csv_lines)

            if csv_content:
                files["wbs"] = ("wbs.csv", csv_content.encode("utf-8"), "text/csv")

        data = {"settings": json.dumps(settings_payload)}

        progress_events = []
        final_result = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                url,
                data=data,
                files=files if files else None,
                headers=self._get_headers(active_api_key),
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise RuntimeError(
                        f"AIX API returned status {response.status_code}: {body.decode('utf-8', errors='replace')}"
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "progress":
                        progress_events.append(event)
                    elif event.get("type") == "result":
                        final_result = event.get("run")
                    elif event.get("type") == "error":
                        raise RuntimeError(f"AIX execution error: {event.get('message')}")

        if not final_result:
            raise RuntimeError("API completed without returning a 'result' event.")

        return progress_events, final_result

    async def recalculate(self, run_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Calls /api/py/recalculate to deterministically recompute FTEs."""
        url = f"{self.base_url}/api/py/recalculate"
        payload = {"run": run_dict}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            res_json = resp.json()
            return res_json.get("run", res_json)

    async def export_excel(self, run_dict: Dict[str, Any]) -> bytes:
        """Calls /api/py/excel to generate an Excel validation workbook."""
        url = f"{self.base_url}/api/py/excel"
        payload = {"run": run_dict}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            return resp.content
