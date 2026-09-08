# 🏭 Blue Yonder Supply Chain Digital Twin

> **AI-powered simulation platform for Blue Yonder SCPO supply planning** — Upload native BY CSV files, simulate risk scenarios, and visualize optimized allocations in seconds.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)](https://nextjs.org)
[![Pyomo](https://img.shields.io/badge/Pyomo-6.7%2B-orange)](https://pyomo.org)
[![HiGHS](https://img.shields.io/badge/HiGHS-1.7%2B-green)](https://highs.dev)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1%2B-yellow)](https://duckdb.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Problem Statement

Enterprise supply chains run on **Blue Yonder (BY) Enterprise Supply Planning** — but the native SCPO input files (`sourcing.csv`, `sku.csv`, +20 more) are **static, deterministic snapshots**. Planners lack a safe sandbox to answer:

> *"What happens if Supplier A loses 30% capacity next week?"*  
> *"How does a 20% demand surge at Location X ripple through the network?"*  
> *"Which alternative lanes absorb the disruption at lowest cost?"*

**Current reality**: Manual what-if analysis in spreadsheets, no solver, no visualization, hours of turnaround.

---

## ✨ Solution

**AI Digital Twin** — A decoupled **Next.js 14 + FastAPI** application that:

| Capability | Description |
|------------|-------------|
| **📁 Native BY Ingestion** | Drag-and-drop 22 SCPO entity types (`if_snop_<entity>-<timestamp>.csv`) |
| **⚠️ Risk Sandbox** | Override source capacity, resource capacity, demand forecasts with instant feedback |
| **🧮 Triple Solver Engine** | **LP (Pyomo + HiGHS)** for optimality • **Heuristic** for speed/fallback • **Demand Pegging** for tri-state (Met/Late/Unmet) fulfillment |
| **📊 Visual Dashboard** | Baseline vs. optimized cost KPIs, allocation tables, production plans, demand waterfall |
| **🔍 Root-Cause Analysis** | Bottleneck tracer classifies: Capacity, Material, Sourcing, Lead-Time constrained orders |
| **🔄 Auto-Fallback** | LP fails → Heuristic takes over seamlessly (`fallback: true` in response) |
| **📤 BY Patch Export** | One-click export of what-if scenario as Blue Yonder-compatible ZIP (patched CSVs + change manifest + UI instructions) |
| **⚡ Compare Mode** | Side-by-side Heuristic vs. LpOpt gap analysis (cost, service, latency, resource saturation) |
| **🛠️ Mitigation Levers** | 1-click toggles: Overtime, Expedite Lanes, Alternate BOMs |
| **🚀 Zero-Friction Start** | One command: `python run.py` (auto venv, deps, parallel launch) |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FRONTEND (Next.js 14)                    │  BACKEND (FastAPI)              │
│  ┌─────────────────────────────────────┐   │  ┌─────────────────────────┐  │
│  │ PlannerCockpit (3 Zones)            │   │  │ FastAPI + Uvicorn       │  │
│  │ 1. File Upload (22 entities)        │   │  │                         │  │
│  │ 2. Risk Sandbox (overrides)         │◄──┼──┤  /run-simulation/       │  │
│  │ 3. Results Dashboard (KPIs, tables) │   │  │  solver=auto|heuristic|lp│
│  └─────────────────────────────────────┘   │  └───────────┬─────────────┘  │
│         │                                   │              │              │
│         ▼                                   ▼              ▼              │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │              OPTIMIZATION ENGINE LAYER                              │  │
│  │  ┌─────────────────────┐  ┌─────────────────────────────────────┐  │  │
│  │  │ LP Engine           │  │ Heuristic Engine                    │  │  │
│  │  │ (Pyomo + HiGHS)     │  │ (Greedy Cost-Sorted Allocation)     │  │  │
│  │  │ • Lane capacity     │  │ • O(L log L) complexity             │  │  │
│  │  │ • Demand fulfillment│  │ • Inventory & safety stock aware    │  │  │
│  │  │ • Production/BOM    │  │ • Scheduled receipts                │  │  │
│  │  │ • Resource caps     │  │ • Always feasible (may be subopt)   │  │  │
│  │  │ • Inventory balance │  └─────────────────────────────────────┘  │  │
│  │  └─────────────────────┘                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │ Demand Pegging Engine (Pyomo + HiGHS)                       │  │  │
│  │  │ • Tri-state: MET / LATE_MET / UNMET per order              │  │  │
│  │  │ • Time-phased supply/demand balance                        │  │  │
│  │  │ • Resource-constrained production                          │  │  │
│  │  │ • BOM explosion with inventory                             │  │  │
│  │  │ • Late penalty & shortage penalty                          │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** (tested on 3.12/3.13)
- **Node.js 20+** & **npm 10+**
- **Git**

### Option 1: Automated Launch (Recommended)

```bash
# Clone
git clone <your-repo-url>
cd sp_digitaltwin

# Cross-platform (Windows/macOS/Linux)
python run.py
```

**What `run.py` does automatically:**
1. ✅ Creates `backend/venv` if missing
2. ✅ Installs/updates Python deps from `backend/requirements.txt`
3. ✅ Runs `npm install` in `frontend/` if `node_modules` missing
4. ✅ Launches **FastAPI on :8000** and **Next.js on :3000** in parallel
5. ✅ Opens separate console windows for each service (Windows) or background processes (Unix)

### Option 2: Platform-Specific Scripts

```bash
# Windows
start_app.bat

# macOS / Linux
chmod +x start_app.sh
./start_app.sh
```

### Option 3: Manual (For Development)

```bash
# Terminal 1 - Backend
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

### Verify Installation

```bash
# Backend health
curl http://localhost:8000/
# {"status": "ok"}

# Environment diagnostic (14 checks)
cd backend && python scripts/verify_env.py
```

---

## 📁 Project Structure

```
sp_digitaltwin/
├── .gitignore
├── start_app.bat           # Windows launcher
├── start_app.sh            # macOS/Linux launcher
├── run.py                  # Cross-platform Python launcher
├── PRD.md                  # Product Requirements
├── ARCHITECTURE.md         # Technical architecture (this doc)
├── README.md               # You are here
│
├── backend/
│   ├── requirements.txt    # 16 pinned deps
│   ├── main.py             # FastAPI app + solver selection
│   ├── models.py           # Pydantic schemas (22 entities)
│   ├── file_parser.py      # CSV parsing & validation
│   ├── optimizer.py        # Unified entry point (strategy pattern)
│   ├── heuristic_engine.py # Greedy LP fallback
│   ├── lpopt_engine.py     # Pyomo + HiGHS LP solver
│   ├── schema_config.py    # Column & primary key definitions
│   ├── scripts/
│   │   └── verify_env.py   # 14-check diagnostic
│   └── app/
│       ├── core/
│       │   ├── __init__.py
│       │   ├── bulk_loader.py     # DuckDB bulk CSV pack loader
│       │   └── calendar_resolver.py
│       ├── optimization/
│       │   ├── __init__.py
│       │   ├── heuristic_engine.py  # Wrapper for main heuristic
│       │   └── demand_engine.py     # Tri-state demand pegging (MET/LATE/UNMET)
│       └── services/
│           ├── __init__.py
│           ├── by_exporter.py           # BY-compatible ZIP export (patched CSVs)
│           ├── by_change_exporter.py    # Change manifest + UI instructions
│           ├── bottleneck_tracer.py     # Root-cause classification
│           ├── mitigation_sandbox.py    # 4 mitigation action types
│           ├── simulation_runner.py     # DuckDB scenario runner
│           └── substitutions.py         # Supersession → substitution rules
│
└── frontend/
    ├── package.json        # Next.js 14, React 18, @xyflow/react, recharts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── next.config.mjs     # API proxy /api/* → localhost:8000
    ├── .env.local
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx        # PlannerCockpit
    │   └── globals.css
    └── src/
        ├── components/
        │   ├── PlannerCockpit.tsx    # Main dashboard (3 zones)
        │   ├── SolverSelector.tsx    # Heuristic / LpOpt / Compare
        │   └── DualSolverComparator.tsx # Side-by-side gap analysis
        └── services/
            └── simulationApi.ts   # API client with gap analysis
    └── .gitignore
```

---

## 🎮 Usage Guide

### 1. Prepare Your BY Files

Export from Blue Yonder using the standard naming pattern:

```
if_snop_sourcing-20240115120000.csv     (REQUIRED)
if_snop_sku-20240115120000.csv          (REQUIRED)
if_snop_locations-20240115120000.csv
if_snop_items-20240115120000.csv
if_snop_network-20240115120000.csv
... (up to 22 entities)
```

### 2. Upload Files

1. Open **http://localhost:3000**
2. Drag & drop CSV files into the upload zone (or click to browse)
3. Verify all 22 entities show ✓ **Uploaded** (green) or **Required** (red) / **Optional** (gray)

### 3. Configure Risk Overrides

| Override Type | Key Format | Example | Effect |
|---------------|------------|---------|--------|
| **Sourcing Capacity** | `ITEM\|SOURCE` | `ITEM_A\|SRC_001` = `0.3` | Reduce capacity by 30% |
| **Resource Capacity** | `RES\|LOC` | `FAB_LINE_1\|LOC_1` = `0.15` | Reduce resource by 15% |
| **Demand Forecast** | `ITEM\|SKULOC` | `ITEM_A\|LOC_1` = `1.2` | Increase demand by 20% |

Click **Add Override** → see it appear in the workspace.

### 4. Select Solver

Dropdown in UI (or `solver` query param):
- **Heuristic** (default): Priority-driven, sub-second, feasible
- **LpOpt**: Global LP via HiGHS, minimizes total landed cost
- **Compare Both**: Runs both in parallel, renders side-by-side gap analysis

### 5. Apply Mitigation Levers (Optional)

| Lever | Effect |
|-------|--------|
| **15% Overtime** | Adds capacity to saturated resources |
| **Expedite Lanes** | Increases primary sourcing lane capacity |
| **Alternate BOMs** | Enables alternate bill-of-materials routes |

### 6. Run Simulation

Click **Run Solver** (or **Run Solver Comparison**) → Results appear in **Decision Dashboard**:
- **KPI Cards**: Revenue Protected, OTIF %, Mitigation Cost, ROI
- **Demand Waterfall**: Stacked bar — Met / Late Met / Unmet (Baseline vs What-If)
- **Bottleneck Table**: Root-cause classification + Quick Mitigate button
- **Shipment & Production Tables**: Detailed allocation
- **Solver Execution Banner**: Selected vs. executed solver

### 7. Export BY Patch Pack

Click **Export** → downloads `planner_what_if_by_patch.zip` containing:
- Patched `if_snop_<entity>-<timestamp>.csv` files (pipe-delimited, BY format)
- `change_manifest.json` — structured change log with financial impact
- `BY_UI_Instructions.txt` — step-by-step manual entry instructions for BY screens

---

## 🔧 API Reference

### POST `/run-simulation/`

```bash
curl -X POST http://localhost:8000/run-simulation/ \
  -F "sourcing=@if_snop_sourcing-20240115120000.csv" \
  -F "sku=@if_snop_sku-20240115120000.csv" \
  -F 'risk_adjustments={"sourcing": {"ITEM_A|SRC_001": 0.3}}' \
  -F "solver=auto"
```

**Response:**
```json
{
  "status": "optimal",
  "method": "lp_highs",
  "fallback": false,
  "baseline": [...],
  "shipments": [...],
  "production": [...],
  "baseline_total_cost": 125000.00,
  "total_cost": 118000.00,
  "solve_time_ms": 1200
}
```

### POST `/upload/`

Single endpoint for all file uploads. Supports both S&OP format (`if_snop_<entity>-YYYYMMDDHHMMSS.csv`) and legacy (`sourcing.csv`, `sku.csv`).

### GET `/entities`

Lists all 22 supported entities with filename patterns.

### GET `/api/v1/workspace/data-summary`

Bulk load a BY workspace directory (22 CSV files) into DuckDB and return topology summary (nodes, lanes, active SKUs, memory footprint).

### POST `/api/v1/simulation/export-by-patch`

Export a what-if scenario as a BY-compatible patch ZIP:
- `files`: Baseline BY CSV files (multipart)
- `scenario_deltas`: JSON array of delta objects
- `scenario_id`: Identifier for the scenario
- `justification`: Business justification
- `financial_impact`: JSON object with cost/revenue estimates

Returns: `application/zip` download.

### Other Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| POST | `/upload-files/` | Validate sourcing + sku only |
| POST | `/upload-snop/` | Validate multiple entities |
| GET | `/snop/entities` | List 22 supported entities |

---

## 🧪 Testing

```bash
# Backend environment verification
cd backend && python scripts/verify_env.py
# 14/14 checks should pass

# Frontend lint & typecheck
cd frontend && npm run lint && npx tsc --noEmit

# Run backend unit tests
cd backend && pytest tests/ -v
```

---

## 📦 Dependencies

### Backend (`backend/requirements.txt`)

```
# API Framework
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
pydantic>=2.7.0
pydantic-settings>=2.2.0

# Data Processing
duckdb>=1.1.0
pandas>=2.2.0
polars>=0.20.26
numpy>=1.26.4

# Optimization
pyomo>=6.7.3
highspy>=1.7.0
scipy>=1.13.0

# Testing
pytest>=8.2.0
httpx>=0.27.0
openpyxl>=3.1.2
```

### Frontend (`frontend/package.json`)

```json
{
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@xyflow/react": "^12.0.0",
    "recharts": "^2.12.0",
    "lucide-react": "^0.378.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.3.0",
    "class-variance-authority": "^0.7.0",
    "axios": "^1.6.8"
  }
}
```

---

## 🐳 Docker Deployment (Production)

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - CORS_ORIGINS=https://your-frontend-domain.com
      - BY_DATA_DIR=/data/by_input
    volumes:
      - ./by_data:/data/by_input
  
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_BASE=https://your-backend-domain.com
```

---

## 🔐 Environment Variables

### Backend (`.env` in `backend/`)

```bash
# Optional: BY workspace directory for bulk loader
BY_DATA_DIR=C:\path\to\by_input_folder

# Optional: Snowflake integration (future)
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PRIVATE_KEY_PATH=
SNOWFLAKE_WAREHOUSE=
```

### Frontend (`.env.local` in `frontend/`)

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

---

## 📈 Roadmap

| Phase | Target | Features |
|-------|--------|----------|
| **MVP (v1.0)** | ✅ Done | Triple solver, 22 entities, 3-zone UI, solver comparison, BY patch export, bottleneck tracer, mitigation levers |
| **v1.1** | Q4 2026 | React Flow SupplyChainGraphTwin, multi-scenario compare, async Celery workers |
| **v1.2** | Q1 2027 | Snowflake historical calibration, demand forecasting ML |
| **v2.0** | Q2 2027 | Gurobi/CPLEX option, SSO, PostgreSQL persistence, WebSocket real-time |

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feat/amazing-feature`
3. Run verification: `python run.py` (or `backend/scripts/verify_env.py`)
4. Commit: `git commit -m 'feat: add amazing feature'`
5. Push: `git push origin feat/amazing-feature`
6. Open Pull Request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **Pyomo** team for the algebraic modeling framework
- **HiGHS** developers for the high-performance open-source solver
- **DuckDB** team for the in-process analytical database
- **Blue Yonder** for SCPO schema specifications
- **Next.js**, **FastAPI**, **Tailwind CSS**, **@xyflow/react** communities

---

## 📞 Support

| Channel | Purpose |
|---------|---------|
| GitHub Issues | Bug reports, feature requests |
| Discussions | Architecture questions, usage help |
| Wiki | Extended documentation, examples |

---

**Built with ❤️ for supply chain planners who need answers, not spreadsheets.**