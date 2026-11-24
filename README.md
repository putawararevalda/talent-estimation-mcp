# Talent Estimation MCP Server

A Model Context Protocol (MCP) server wrapping **AIX** (Talent Estimation Agent) with dual-methodology workload sizing (Use Case Points and Bottom-Up), capability matching, and AI augmentation analysis.

Built to run seamlessly both **in the cloud on [Labs Playdev](https://labs.playdev.online)** (via Server-Sent Events / SSE) and **locally** (via stdio).

---

## Features

- **Dual-Method Sizing (`estimate_wbs`):** Evaluates WBS tasks against capability rubrics using both **Use Case Points (UCP)** and **Bottom-Up (BU)** FTE estimation.
- **Role & Gap Detection:** Identifies unassigned tasks, missing role competencies (e.g. DE, DA, DS, AI, UXR, UX, UI), and task overlaps.
- **AI Augmentation Savings:** Computes potential person-days and FTE saved via generative AI tooling across 7 standard categories.
- **Zero-Token Deterministic Recalculation (`recalculate_plan`):** Adjust hours/day, days/month, support factor, or role headcount targets and re-evaluate immediately without re-calling LLM models.
- **Auditable Excel Export (`export_validation_excel`):** Downloads the complete multi-sheet calculation workbook.
- **Built-in Run Caching:** Caches ~90KB run results on the server and passes lightweight `run_id` tokens to keep LLM context concise.

---

## Deployment on Labs Playdev

Deploy directly from the **Labs Playdev** dashboard:

1. Click **Create Static App** -> **Manual**.
2. Fill in the parameters:
   - **App name:** `talent-estimation-mcp`
   - **Docker image:** `skos/dind:python`
   - **Repository URL:** `https://github.com/putawararevalda/talent-estimation-mcp.git`
   - **Work dir:** `/data/talent-estimation-mcp`
   - **Startup command:**
     ```bash
     pip install -r requirements.txt && python server.py --port 80
     ```
   - **CPU / Memory:** 1 Core, 512 MB (or 1 GB).
3. Click **Create**.
4. Once deployed, your MCP SSE URL will be available at:
   ```
   https://<your-app-id>.labs.playdev.online/sse
   ```

---

## Local Usage & Testing

### 1. Setup Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run as SSE Server (Port 8000 for local test)
```bash
python server.py --port 8000
```
- Health probe: `http://localhost:8000/health`
- SSE Endpoint: `http://localhost:8000/sse`

### 3. Run with stdio (for Claude Desktop / Local Agent)
```bash
python server.py --stdio
```

---

## Client Configuration

### Connecting via SSE (Labs Playdev or Remote URL)

Add to your MCP configuration file (e.g. `claude_desktop_config.json` or `antigravity.json`):

```json
{
  "mcpServers": {
    "talent-estimation": {
      "url": "https://<your-app-id>.labs.playdev.online/sse"
    }
  }
}
```

### Connecting via stdio (Local Python)

```json
{
  "mcpServers": {
    "talent-estimation": {
      "command": "python",
      "args": ["/path/to/talent-estimation-mcp/server.py", "--stdio"],
      "env": {
        "AIX_BASE_URL": "https://93id1-aix.labs.playdev.online"
      }
    }
  }
}
```

---

## Available Tools

| Tool | Description |
| :--- | :--- |
| `health_check()` | Tests remote AIX API connectivity and server status. |
| `get_capability_catalog(team)` | Retrieves capability areas, skills, and scope definitions for `data` or `design` teams. |
| `estimate_wbs(...)` | Evaluates WBS tasks, computes dual FTEs, identifies gaps/overlaps, and returns a `run_id`. |
| `recalculate_plan(...)` | Deterministically recalculates a plan by `run_id` with updated hours, days, or role inputs. |
| `export_validation_excel(...)` | Downloads the full `.xlsx` audit sheet for a given `run_id`. |
