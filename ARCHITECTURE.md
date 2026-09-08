# System Architecture Document - AI Digital Twin for Supply Planning

## 1. Overview

This document describes the technical architecture for the MVP AI Digital Twin Parameter Interceptor & Simulator for Supply Planning. The system enables planners to upload Blue Yonder SCPO schema files, simulate risk scenarios, and visualize optimized supply chain allocations through an interactive web interface.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER (Next.js 14)                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ File Upload Zone │  │ Risk Sandbox     │  │ Results Dashboard        │  │
│  │ (22 BY entities) │  │ Workspace        │  │ (Cost comparison, tables)│  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────────┬─────────────┘  │
│           │                     │                          │               │
│           └─────────────────────┼──────────────────────────┘               │
│                                 ▼                                          │
│                    ┌─────────────────────┐                                 │
│                    │   API Proxy (/api/*) │                                 │
│                    └──────────┬──────────┘                                 │
└───────────────────────────────┼────────────────────────────────────────────┘
                                │ HTTPS / HTTP (dev)
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          APPLICATION LAYER (FastAPI)                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Ingestion    │ │ Validation   │ │ Simulation   │ │ Solver Selection │  │
│  │ Endpoint     │ │ Firewall     │ │ Engine       │ │ (auto/h/lp)      │  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘  │
│         │                │                │                    │           │
│         └────────────────┼────────────────┼────────────────────┘           │
│                          ▼                                                │
│              ┌─────────────────────────────────────┐                      │
│              │     Optimization Engine Layer       │                      │
│              │  ┌─────────────┐ ┌───────────────┐  │                      │
│              │  │ LP Engine   │ │ Heuristic     │  │                      │
│              │  │ (Pyomo +    │ │ Engine        │  │                      │
│              │  │  HiGHS)     │ │ (Greedy LP)   │  │                      │
│              │  └─────────────┘ └───────────────┘  │                      │
│              └─────────────────────────────────────┘                      │
└────────────────────────────────┼──────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DATA SOURCES                                      │
│  ┌─────────────────────┐  ┌─────────────────────────────────────────────┐  │
│  │ Blue Yonder SCPO    │  │ 22 Entity Types Supported                    │  │
│  │ CSV Files           │  │ (sourcing, sku, locations, items, network,   │  │
│  │ • sourcing.csv      │  │  calendars, calpattern, calattribute,       │  │
│  │ • sku.csv           │  │  customer, customerorder, dfutoskufcst,      │  │
│  │ • +20 optional      │  │  inventory, skueffinventoryparam,            │  │
│  └─────────────────────┘  │  schedrcpts, supersession, billofmaterials, │  │
│                           │  altbillofmaterials, productionmethod,       │  │
│                           │  productionstep, altproductionstep, res,     │  │
│                           │  purchmethod)                                │  │
│                           └─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 Frontend (Next.js 14 / React 18 / TypeScript)

| Component | Responsibility | Technology |
|-----------|---------------|------------|
| **PlannerCockpit** (`page.tsx`) | Main dashboard orchestrating 3 zones | Next.js App Router, React 18 |
| **File Upload Zone** | Drag-and-drop 22 BY CSV entities, pattern validation | Tailwind CSS, native Drag & Drop API |
| **Risk Sandbox Workspace** | Interactive overrides for capacity/demand/forecast | React Hooks, controlled forms |
| **Results Dashboard** | Side-by-side baseline vs optimized, KPI cards | Recharts, custom tables |
| **SupplyChainGraphTwin** | React Flow DAG visualization of network | @xyflow/react v12 |
| **SolverSelector** | Dropdown: auto / heuristic / LP | React Select |
| **API Client** | REST communication with FastAPI backend | Axios with interceptors |

### 3.2 Backend (Python FastAPI)

| Module | Responsibility | Key Technologies |
|--------|---------------|------------------|
| `main.py` | App initialization, routing, CORS, health checks, solver selection | FastAPI, Uvicorn |
| `models.py` | Pydantic validation schemas for 22 BY entity types | Pydantic v2, Pandas |
| `file_parser.py` | CSV parsing, column normalization (uppercase), filename pattern extraction | Pandas, io.BytesIO, regex |
| `optimizer.py` | Unified entry point with solver selection (auto/heuristic/lp) | Strategy pattern |
| `heuristic_engine.py` | Greedy cost-minimization fallback (O(n log n) lanes) | NumPy, Pandas |
| `lpopt_engine.py` | Full LP optimization using Pyomo + HiGHS via APPSI | Pyomo, pyomo.contrib.appsi, HiGHS |
| `scripts/verify_env.py` | 14-check diagnostic: imports, solver, DuckDB, Polars | Standalone script |

### 3.3 Optimization Engine

#### LP Engine (`lpopt_engine.py`) - Primary Solver
| Element | Specification |
|---------|---------------|
| Model Type | `ConcreteModel` (in-memory) |
| Objective | Minimize Σ (Units Shipped × Unit Base Cost) + Production run cost |
| Decision Variables | Shipment qty per (ITEM, SOURCE, DEST); Production qty per (ITEM, LOC, METHOD) |
| Constraints | • Lane capacity<br>• Demand fulfillment (≥)<br>• Resource capacity<br>• Inventory balance (safety stock)<br>• BOM component consumption<br>• Non-negativity |
| Solver | HiGHS via `pyomo.contrib.appsi` (native Python, no license) |
| Advanced Features | Production methods, BOM explosion, Resource constraints, Scheduled receipts, Safety stock |

#### Heuristic Engine (`heuristic_engine.py`) - Fallback
| Element | Specification |
|---------|---------------|
| Algorithm | Greedy cost-sorted lane allocation per (ITEM, DEST) |
| Complexity | O(L log L) where L = number of lanes |
| Use Case | Fast fallback when LP infeasible/error; warm-start; large-scale screening |
| Features | Inventory offset, safety stock, scheduled receipts, risk-adjusted capacity |

#### Solver Selection Strategy (`optimizer.py`)
| Mode | Behavior |
|------|----------|
| `auto` (default) | Try LP first; on error/infeasible → fallback to heuristic |
| `lp` | Force Pyomo + HiGHS; return error if fails |
| `heuristic` | Force greedy; always returns feasible (may be suboptimal) |

---

## 4. Data Flow

### 4.1 Ingestion Flow
```
User drops CSV files (if_snop_<entity>-<timestamp>.csv)
        │
        ▼
Next.js: Parse files → FormData → POST /run-simulation/
        │
        ▼
FastAPI: Receive multipart → file_parser.read_and_normalize_csv() → UPPERCASE columns
        │
        ▼
Validation Firewall: Pydantic models (SourcingInput, SKUInput, ENTITY_SCHEMA_MAP) → 422 if invalid
        │
        ▼
Return: Validated DataFrames → Pass to optimizer
```

### 4.2 Simulation Flow
```
User adjusts risk overrides (SOURCE capacity, RESOURCE capacity, DEMAND multiplier)
        │
        ▼
Next.js: POST /run-simulation/ { sourcing, sku, risk_adjustments, optional_files, solver }
        │
        ▼
FastAPI: optimizer.run_optimization(..., solver="auto")
        │
        ├──▶ LP Engine (Pyomo + HiGHS)
        │       └─▶ ConcreteModel → Sets/Params/Vars/Constraints → HiGHS → Optimal
        │
        └──▶ Heuristic Engine (fallback)
                └─▶ Greedy allocation → Feasible solution
        │
        ▼
FastAPI: Format results → JSON { baseline, optimized, deltas, metrics, status, method }
        │
        ▼
Next.js: Render comparison dashboard (KPIs, tables, charts)
```

---

## 5. API Contract

### 5.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check → `{"status": "ok"}` |
| POST | `/upload-files/` | Upload & validate sourcing.csv + sku.csv |
| POST | `/upload-snop/` | Upload & validate multiple S&OP entities (22 types) |
| GET | `/snop/entities` | List supported entities & filename pattern |
| POST | `/run-simulation/` | Execute optimization with risk params & solver selection |

### 5.2 Simulation Request (multipart/form-data)
```
sourcing: File (required)
sku: File (required)
risk_adjustments: JSON string (e.g., {"sourcing": {"SRC_001": 0.3}, "dfutoskufcst": {"ITEM_A|LOC_1": 1.2}})
solver: "auto" | "heuristic" | "lp" (query param, default: "auto")
bom: File (optional)
res: File (optional)
productionmethod: File (optional)
productionstep: File (optional)
inventory: File (optional)
schedrcpts: File (optional)
```

### 5.3 Simulation Response
```json
{
  "status": "optimal" | "infeasible" | "error",
  "method": "lp_highs" | "greedy_heuristic",
  "fallback": boolean,
  "original_error": "string (if fallback)",
  "baseline": [...],
  "shipments": [...],
  "production": [...],
  "baseline_total_cost": 125000.00,
  "total_cost": 118000.00,
  "solve_time_ms": 1200
}
```

---

## 6. Data Models (Blue Yonder SCPO Schema)

### 6.1 Core Entities (Required)

| Entity | File Pattern | Key Fields |
|--------|--------------|------------|
| **Sourcing** | `if_snop_sourcing-*.csv` | ITEM, SOURCE, DEST, BASE_COST, MAX_CAPACITY |
| **SKU** | `if_snop_sku-*.csv` | ITEM, LOC, DEMAND, PRIORITY |

### 6.2 Extended Entities (Optional - 20 types)

| Category | Entities |
|----------|----------|
| **Master Data** | locations, items, network, calendars, calpattern, calattribute |
| **Demand** | customer, customerorder, dfutoskufcst |
| **Supply** | inventory, skueffinventoryparam, schedrcpts, supersession |
| **Production** | billofmaterials, altbillofmaterials, productionmethod, productionstep, altproductionstep, res |
| **Procurement** | purchmethod |

---

## 7. Risk Override Schema

| Override Type | Key Format | Value | Effect |
|---------------|------------|-------|--------|
| `sourcing` | `SOURCE_ID` (e.g., `SRC_001`) | Capacity reduction % (0.0-1.0) | Reduces MAX_CAPACITY for all lanes from that source |
| `res` | `RESOURCE_ID` (e.g., `RES_001`) | Capacity reduction % (0.0-1.0) | Reduces resource capacity for production steps |
| `dfutoskufcst` | `ITEM\|LOC` (e.g., `ITEM_A\|LOC_1`) | Demand multiplier (e.g., 1.2 = +20%) | Scales DEMAND for that item-location |

---

## 8. Error Handling & Resilience

| Scenario | Handling Strategy |
|----------|-------------------|
| Missing required columns | FastAPI returns 422 with field-level errors |
| Infeasible LP optimization | Auto-fallback to heuristic; return `fallback: true` |
| Solver timeout | Return partial results + `status: "timeout"` |
| Division by zero / math errors | Catch in optimizer, return 500 with sanitized message |
| Large file upload | Streaming parse, chunked processing (future) |
| Invalid risk JSON | 400 with parse error details |

---

## 9. Security

- **Transport**: HTTPS/TLS 1.3 enforced (production); HTTP allowed for localhost dev
- **CORS**: Restricted to frontend origin in production; `*` for dev
- **Authentication**: JWT/OAuth2 via proxy (future); API keys for Snowflake
- **Input Validation**: Pydantic strict mode, column allowlist, filename pattern enforcement
- **Secrets**: Snowflake credentials via environment variables, never logged

---

## 10. Deployment Topology

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Vercel /      │────▶│  Railway /      │────▶│  Snowflake      │
│   Netlify       │     │  Fly.io /       │     │  SQL API        │
│   (Next.js 14)  │     │  Render         │     │                 │
└─────────────────┘     │  (FastAPI)      │     └─────────────────┘
                        │                 │
                        │  ┌───────────┐  │
                        │  │  HiGHS    │  │
                        │  │ (bundled) │  │
                        │  └───────────┘  │
                        └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  Browser        │
                        │  (Planner)      │
                        └─────────────────┘
```

- **Frontend**: Vercel/Netlify (static + SSR, Edge functions)
- **Backend**: Railway / Fly.io / Render (containerized FastAPI, auto-scaling)
- **Solver**: HiGHS binary bundled in container (no external service)
- **Snowflake**: Existing corporate account, SQL API endpoint (future)

---

## 11. Development Workflow

### Local Development
```bash
# Option 1: Automated (recommended)
python run.py                    # Cross-platform launcher
# or
start_app.bat                    # Windows
./start_app.sh                   # macOS/Linux

# Option 2: Manual
# Terminal 1 - Backend
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

### Testing
```bash
# Backend
cd backend
python scripts/verify_env.py      # Environment diagnostic
pytest tests/                     # Unit tests (future)

# Frontend
cd frontend
npm run lint                      # ESLint
npm run typecheck                 # tsc --noEmit
```

### CI/CD Pipeline (GitHub Actions)
```yaml
# .github/workflows/ci.yml
- Lint: ruff (backend), eslint (frontend)
- Typecheck: mypy (backend), tsc (frontend)
- Test: pytest + httpx TestClient (backend)
- Build: Docker multi-stage → push to registry
- Deploy: Railway/Fly.io (backend), Vercel (frontend)
```

---

## 12. Project Structure

```
sp_digitaltwin/
├── .gitignore                    # Unified ignore patterns
├── start_app.bat                 # Windows launcher (auto venv + npm + parallel start)
├── start_app.sh                  # macOS/Linux launcher (auto venv + npm + parallel start)
├── run.py                        # Cross-platform Python launcher
├── PRD.md                        # Product Requirements Document
├── ARCHITECTURE.md               # This document
├── README.md                     # Project overview & quick start
├── backend/
│   ├── requirements.txt          # 16 pinned dependencies
│   ├── main.py                   # FastAPI app with solver selection
│   ├── models.py                 # Pydantic schemas (22 entities)
│   ├── file_parser.py            # CSV parsing & validation
│   ├── optimizer.py              # Unified entry point (strategy pattern)
│   ├── heuristic_engine.py       # Greedy LP fallback (O(n log n))
│   ├── lpopt_engine.py           # Pyomo + HiGHS LP solver
│   └── scripts/
│       └── verify_env.py         # 14-check environment diagnostic
└── frontend/
    ├── package.json              # Next.js 14, React 18, @xyflow/react, recharts, axios
    ├── tsconfig.json             # TypeScript config with @/* aliases
    ├── tailwind.config.ts        # Tailwind + dark mode + custom colors
    ├── postcss.config.js         # PostCSS + autoprefixer
    ├── next.config.mjs           # API proxy rewrites /api/* → localhost:8000
    ├── .env.local                # NEXT_PUBLIC_API_BASE=http://localhost:8000
    ├── app/
    │   ├── layout.tsx            # Root layout + metadata
    │   ├── page.tsx              # PlannerCockpit (SimulationDashboard)
    │   └── globals.css           # Tailwind + custom components
    └── .gitignore
```

---

## 13. Versioning

| Version | Date | Changes |
|---------|------|---------|
| **1.0.0** | 2026-09-04 | MVP Release: Core LP + Heuristic engines, 22 BY entities, 3-zone UI, solver selection, automated launchers |
| **0.9.0** | 2026-09-01 | Beta: Pyomo + HiGHS integration, basic dashboard, file upload |
| **0.5.0** | 2026-08-15 | Alpha: Heuristic engine, FastAPI skeleton, Next.js scaffold |

---

## 14. Future Extensibility (Post-MVP)

| Area | Enhancement | Priority |
|------|-------------|----------|
| **Async Processing** | Celery + Redis for long-running solves (>30s) | High |
| **Multi-scenario** | Compare N risk scenarios in single run (batch) | High |
| **Persistence** | PostgreSQL for session history, audit trail, warm-starts | Medium |
| **Auth** | SSO integration (Okta/Azure AD), RBAC | Medium |
| **Advanced Solvers** | Gurobi/CPLEX option for enterprise (via Pyomo) | Low |
| **Real-time** | WebSocket for solve progress updates, cancellation | Low |
| **Graph Twin** | Full React Flow DAG with node/edge editing, what-if drag | High |
| **Snowflake** | Historical fill rates, lead time calibration, auto-risk | Medium |
| **Export** | Download optimized plans as BY-compatible CSV | High |

---

## 15. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Dual-engine (LP + Heuristic)** | LP for accuracy; Heuristic for speed/fallback; Auto-selection for UX |
| **Pyomo + HiGHS (APPSI)** | No commercial license; native Python; high performance; active development |
| **Next.js 14 App Router** | React Server Components, streaming, better SEO, modern patterns |
| **@xyflow/react v12** | Best-in-class React DAG library; MIT license; TypeScript native |
| **Tailwind CSS** | Utility-first, dark mode, small bundle, design system ready |
| **22 BY Entities** | Full SCPO coverage; planners use native files without transformation |
| **Filename Pattern Enforcement** | `if_snop_<entity>-<timestamp>.csv` matches BY convention; prevents mis-uploads |
| **Solver Selection via Query Param** | Simple, testable, no session state; `solver=auto|heuristic|lp` |

---

## 16. Performance Targets (NFR)

| Metric | Target | Measurement |
|--------|--------|-------------|
| API Latency (health) | < 50ms | `/` endpoint |
| File Upload (10MB) | < 2s | Multipart parsing + validation |
| LP Solve (1000 lanes) | < 5s | End-to-end `/run-simulation/` |
| Heuristic Solve (10000 lanes) | < 500ms | Fallback path |
| Frontend FCP | < 1.5s | Lighthouse |
| Frontend TTI | < 3s | Lighthouse |

---

*Document Version: 2.0 | Last Updated: 2026-09-04 | Author: AI Digital Twin Team*