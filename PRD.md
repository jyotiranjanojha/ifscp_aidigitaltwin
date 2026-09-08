# Product Requirement Document (PRD) - MVP

## Document Control
*   **Title:** MVP AI Digital Twin Parameter Interceptor & Simulator for Supply Planning
*   **Target Core Context:** Blue Yonder (BY) SCPO Input Schema Files (`sourcing.csv`, `sku.csv`)
*   **Application Architecture:** Decoupled Next.js UI Frontend + Python FastAPI Backend Microservice
*   **Core Mathematical Engine:** Pyomo Optimization Modeling Framework + HiGHS Solver Engine
*   **Data Enrichment Source:** Snowflake SQL API (Historical Baseline Performance Logs)
*   **Status:** Final Draft (Analytical Sandbox Scope)
*   **Version:** 3.0
*   **Author:** Lead Enterprise Architect / AI Specialist

---

## 1. Problem Statement & Business Context

### 1.1 Context
The enterprise utilizes **Blue Yonder Enterprise Supply Planning (BY ESP)** to manage master scheduling, factory resource balancing, and constraint-based deployment. The data pipelines rely heavily on flat structural file exchanges: raw operational datasets are periodically queried from upstream repositories, formatted into standard **SCPO Schema CSV files**, and placed into landing folders for BY ingestion loops.

### 1.2 Core Vulnerabilities & MVP Pivot
While these flat files represent the official input rules for Blue Yonder, they remain rigid, deterministic, and static snapshot views of the supply chain network. Planners lack an isolated operational playground to visualize what happens *on top* of these files when an unexpected disruption strikes mid-cycle. 

This Minimum Viable Product (MVP) completely shifts focus from generating output files to creating an **Analytical Simulation Canvas**. It builds an independent application that **ingests native Blue Yonder input files, maps their column attributes into an active in-memory mathematical graph network via Pyomo, applies user-controlled risk parameters, and displays optimized alternative outcomes instantly inside a responsive web browser window.**

---

## 2. Solution Architecture Blueprint

The application functions as a zero-overhead middleware sandbox. It reads the specific data tables meant for Blue Yonder, validates their headers, maps them into an in-memory optimization graph, and visually presents alternative supply lane options.

  [ Raw BY Input Files ] ──(Manually Drop into App)──> [ Next.js UI / FastAPI Middleware ]
 (sku.csv, sourcing.csv, etc.)                                      │
                                                           - Reads BY Native Layouts
                                                           - Triggers Risk Sandbox Sliders
                                                                    │
                                                                    ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                            AI TWIN VISUAL SIMULATION WORKSPACE (PYOMO)                         │
 │                                                                                                │
 │   1. BINDING & PARSING ZONE                                                                    │
 │      - Directly maps the native BY `ITEM`, `LOC`, `SOURCE`, and `DEST` headers into Pandas.    │
 │      - Pulls matching historical validation variables dynamically from Snowflake SQL API.      │
 │                                                                                                │
 │   2. RISK ADJUSTMENT PLAYGROUND                                                                │
 │      - User simulates changes *on top* of the BY baseline file parameters inside Next.js UI.   │
 │                                                                                                │
 │   3. COMPUTE & OPTIMIZATION MATRIX                                                             │
 │      - Pyomo matches the BY constraint rules (such as capacities and demands) in memory.       │
 │      - The HiGHS solver engine calculates the alternative, risk-adjusted network outputs.      │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                    │
                                                                    ▼
                      [ Next.js Visual UI Dashboard Screen ]
                      - Renders side-by-side cost impact metrics and delta cards.
                      - Displays your "What-If" optimized allocations directly against BY baseline rows.


### 2.1 Key MVP Value Propositions
*   **Direct Blue Yonder File Ingestion:** The twin directly understands and reads native BY parameters (`ITEM`, `SOURCE`, `DEST`, `MAX_CAPACITY`), eliminating the need for custom database connectors.
*   **Decoupled Microservice Speed:** The client-side interface (**Next.js / React**) stays lightning-fast and responsive, using clean REST API requests to communicate with an asynchronous computational layer (**Python FastAPI**).
*   **Advanced Simulation Playground:** By leveraging **Pyomo** paired with the modern **HiGHS solver**, planners can manipulate sliders to simulate capacity failures and visually track optimized alternative allocations instantly.

---

## 3. High-Level Design (HLD) & Technology Stack

### 3.1 Technology Stack Matrix

| Architectural Layer | Recommended Technology | Rationale for Selection |
| :--- | :--- | :--- |
| **User Interface (UI)** | `Next.js / React.js` + Tailwind CSS | Renders modern browser command dashboards allowing planners to upload CSVs, adjust risk parameters, and visualize results. |
| **Application Backend** | `Python FastAPI` | A lightweight, fast asynchronous microservice framework that handles incoming multi-part files and JSON endpoints. |
| **Data Fetch Interface** | `Snowflake SQL API` | Connects backend endpoints to corporate performance logs via REST queries, removing heavy local database client overhead. |
| **File Processing Engine** | `Pandas` | Standardizes data extraction and handles missing values, converting raw BY matrix tables into clean dictionaries. |
| **Data Validation Rules**  | `Pydantic` Data Models | Functions as an application firewall to verify incoming file schemas conform exactly to BY SCPO structures. |
| **Modeling Framework** | `Pyomo (Python Optimization)` | Premium optimization modeling framework providing clean programmatic constraints declarations and complete solver independence. |
| **Engine Math Solver** | `HiGHS (via Appsi / Anaconda)` | A cutting-edge open-source solver bundled natively inside Python, eliminating commercial licensing friction for the MVP. |

---

## 4. Functional Requirements

### 4.1 BY File Ingestion, Parsing, & Firewall Protection
*   **FR-1.1:** The Next.js web application must provide a drag-and-drop file upload component built specifically to ingest native Blue Yonder input files (`sourcing.csv`, `sku.csv`).
*   **FR-1.2:** The FastAPI backend must translate all incoming column layouts into uppercase characters to conform to standard SCPO schema definitions.
*   **FR-1.3:** The backend data firewall must verify that critical operational arrays—such as `ITEM`, `SOURCE`, `DEST`, `BASE_COST`, and `MAX_CAPACITY`—are present. If missing, it must instantly isolate the dataset, reject execution, and send structural alerts back to the frontend window.

### 4.2 Visual Risk Sandbox Workspace
*   **FR-2.1:** The Next.js console must expose interactive workspace control components (sliders, forms) letting planners layer adjustments (e.g., manually dropping a primary supplier's capacity) over the initial file values.
*   **FR-2.2:** The backend must connect to the Snowflake SQL API using secure authorization headers to fetch historical performance trends and validate sandbox assumptions dynamically behind the scenes.
*   **FR-2.3:** The dashboard view layer must render side-by-side analytical summaries, contrasting original input matrix parameters against the newly calculated alternative solutions.

### 4.3 Pyomo Mathematical Modeling Engine
*   **FR-3.1:** The application must map structural BY matrix columns directly into a Pyomo `ConcreteModel` in-memory graph layout.
*   **FR-3.2:** The objective function inside the Pyomo routine must calculate and **Minimize Total Landed Cost** (Units Shipped × Unit Base Cost) across all processed lanes.
*   **FR-3.3:** The model constraints must guarantee that calculated shipment values never breach maximum capacity limits defined by the input files, while completely fulfilling total customer network demand.
*   **FR-3.4:** The backend must trigger the native `HiGHS` solver engine over optimized interfaces (`pyomo.contrib.appsi`) to isolate logic execution.

---

## 5. Non-Functional & Decoupling Guardrails

### 5.1 System Decoupling Rules
*   **NFR-1.1 (Operational Isolation):** The application must remain completely detached from both the live Snowflake data lakehouse and the production Blue Yonder cloud tables. It must act strictly as a safe, exploratory analytical window.
*   **NFR-1.2 (Failure Sandboxing):** Mathematical anomalies, division-by-zero errors, or unfeasible optimization parameters within the simulation workspace must be caught and handled safely inside the application runtime, ensuring the interface never crashes or displays raw trace logs to the planner.

### 5.2 Performance & Security Controls
*   **NFR-2.1 (Response Latency):** The Pyomo mathematical modeling engine and underlying HiGHS solver must calculate alternative routing permutations and return the optimized JSON matrix back to the Next.js screen in under 5 seconds.
*   **NFR-2.2 (Security Protocol Standards):** All data transmissions occurring between the user’s web browser, the FastAPI microservice, and the Snowflake SQL API must be encrypted via HTTPS / TLS 1.3 channels.