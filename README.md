# AI-Powered Observability Platform

A self-healing observability platform built on a microservices-based e-commerce application. It collects metrics, logs and traces from five services, detects anomalies, identifies which service is actually at fault, and decides what to do about it — evaluated against ground truth from controlled fault injection.

The distinguishing feature is that every stage is measured rather than asserted. Faults are injected with known type, target and severity, so detection latency, root-cause accuracy and remediation decisions are all scored automatically against recorded labels.

---

## 🚀 Features

- Microservices-based e-commerce application
- Dockerized deployment using Docker Compose
- Distributed tracing with OpenTelemetry and Jaeger
- Metrics collection using Prometheus
- Interactive dashboards with Grafana
- Centralized logging with Loki
- Fault injection across 8 fault types at 3 severity levels
- Multimodal telemetry pipeline combining metrics, logs and traces
- Anomaly detection with a statistical baseline and a trained Isolation Forest
- Root cause analysis using the observed service dependency graph
- Remediation engine with safety guardrails, running in dry-run
- Automated evaluation against ground-truth fault labels

---

## 🏗️ Architecture

```
                        +----------------------+
                        |       Grafana        |
                        +----------+-----------+
                                   |
          +------------------------+------------------------+
          |                        |                        |
    +-----v-----+          +-------v------+         +-------v------+
    | Prometheus|          |     Loki     |         |    Jaeger    |
    +-----+-----+          +-------+------+         +-------+------+
          |                        |                        |
          +-----------+------------+------------+-----------+
                      |                         |
          +-----------v-------------------------v-----------+
          |           Microservices Platform                |
          |                                                 |
          |  User Service      Product Service              |
          |  Cart Service      Order Service                |
          |  Payment Service                                |
          +-------------------------+-----------------------+
                                    |
                                    v
                        +-----------------------+
                        |     AI Engine         |
                        |                       |
                        |  collect  -> detect   |
                        |  localise -> remediate|
                        |          -> verify    |
                        +-----------------------+
```

---

## 🔁 The Pipeline

```
  Telemetry (metrics + logs + traces), every 10s
                    |
                    v
  Feature extraction  -  12 features per service, 30s windows
                    |
                    v
  Detection  -  rule layer + z-score baseline / Isolation Forest
                    |
             anomaly detected
                    v
  Root cause  -  walk the dependency graph from traces
                    |
                    v
  Remediation  -  runbook -> guardrails -> dry-run executor
                    |
                    v
  Verification  -  did metrics return to baseline?
                    |
          +---------+---------+
          v                   v
      Recovered          Escalate
```

**Detection** runs two detectors behind one interface so they stay directly comparable. A deterministic rule layer handles conditions that are assertions rather than inferences — a service that fails to scrape is down, and no model should be asked to confirm that.

**Root cause** matters because failures propagate. Stop the product database and three services look unhealthy, with the *caller* usually alarming first. The engine walks the call graph observed in the traces and discards any anomalous service that calls another anomalous one, leaving the service nothing else depends on.

**Remediation** maps a symptom class to an action through a readable table rather than a learned policy, so every action can be predicted and audited. Nothing executes: intended actions are logged with their reasoning, which is how action precision is measured before the system is trusted to act.

---

## 📊 Results

From a campaign of 16 episodes spanning 8 fault types and 3 severity levels, with models trained only on fault-free traffic:

| | Detected | Root cause correct | False alarms |
|---|---|---|---|
| Statistical baseline | 14/15 | 13/15 | 5 |
| Isolation Forest | 9/15 | 5/15 | 14 |

Detection latency ranges from 13 to 61 seconds depending on fault type and severity.

Detection degrades with severity as expected — the baseline catches 8/8 severe, 4/4 moderate and 2/3 subtle faults — which confirms the severity variants produce a meaningful difficulty gradient rather than only obvious failures.

The statistical baseline currently outperforms the Isolation Forest. The measured reason is that the baseline workload deliberately cycles load levels, so absolute throughput and CPU vary more under normal operation than they do during most faults, which is exactly the condition an unsupervised point-anomaly detector handles badly. The baseline is retained permanently as the floor any model has to beat.

---

## 📦 Microservices

### User Service
- JWT Authentication
- Password hashing with bcrypt
- User management APIs

### Product Service
- Product CRUD operations
- PostgreSQL with Prisma ORM

### Cart Service
- Redis-backed shopping cart
- Zod validation
- Fast cart operations

### Order Service
- Order orchestration
- Atomic stock updates
- Saga-style failure handling

### Payment Service
- Idempotent payment APIs
- Configurable delay injection
- Configurable payment failure simulation

---

## 📊 Observability Stack

| Tool | Purpose |
|------|---------|
| Prometheus | Metrics Collection |
| Grafana | Dashboards & Visualization |
| Loki | Centralized Logging |
| Jaeger | Distributed Tracing |
| OpenTelemetry | Instrumentation |
| Winston | Structured Logging |

---

## 🤖 AI Pipeline

Telemetry is collected from all five services every 10 seconds and written as versioned snapshots. Each snapshot keeps metrics, logs and traces in separate blocks, so the contribution of each modality can be measured independently.

Collected per service:

| Source | Signals |
|---|---|
| Metrics | latency (p95), error rate, request rate, CPU, memory, availability |
| Logs | error, warning and total log counts |
| Traces | span counts, span error rate, span latency, downstream call counts |
| Graph | caller → callee edges observed in traces |

Feature extraction turns these into 12 columns per service over 30-second windows: eight describing the window and four describing relative change from the previous one. Absolute values say what a service is doing; change values say whether it is degrading.

Models are trained on normal traffic only. Labelled fault windows are excluded with a margin either side, and idle samples are excluded too — an idle system is not a healthy one, and mixing them teaches the model that zero traffic is normal.

---

## ⚠️ Fault Injection

Eight fault types are injected at runtime without restarting or rebuilding any service. Each injection records its type, target service and severity, producing ground truth automatically.

| Fault | Category | Severity levels |
|---|---|---|
| payment-failure | application | subtle / moderate / severe |
| payment-delay | application | subtle / moderate / severe |
| db-delay | database | subtle / moderate / severe |
| memory-leak | resource | subtle / moderate / severe |
| cpu-stress | resource | binary |
| db-down | database | binary |
| redis-down | infrastructure | binary |
| service-crash | infrastructure | binary |

Severity levels matter for evaluation: a detector that only catches a 30% error rate has not been tested against a 2% one.

```powershell
# list available faults
.\faults\run-fault.ps1 -List

# inject and recover
.\faults\run-fault.ps1 -Fault payment-failure -Action inject -Severity subtle
.\faults\run-fault.ps1 -Fault payment-failure -Action recover
```

---

## 🛠️ Tech Stack

### Backend
- Node.js
- Express.js
- Prisma ORM

### Databases
- PostgreSQL
- Redis

### Observability
- Prometheus
- Grafana
- Loki
- Jaeger
- OpenTelemetry

### AI
- Python
- scikit-learn
- NumPy

### Load Generation
- k6

### DevOps
- Docker
- Docker Compose

---

## 📁 Project Structure

```
AI-Powered-Observability-Platform
│
├── ai-engine/
│   ├── collectors/          Prometheus, Loki and Jaeger collectors
│   ├── remediation/         runbook, guardrails, executors, engine
│   ├── features_compact.py  feature extraction
│   ├── train.py             Isolation Forest training
│   ├── detect.py            detection and root cause analysis
│   └── remediate.py         remediation replay and scoring
│
├── faults/
│   ├── definitions/         fault definitions by category
│   └── run-fault.ps1        injection with ground-truth labelling
│
├── load/                    k6 load profiles
├── observability/           Prometheus, Grafana and Loki configuration
├── services/
│   ├── user-service/
│   ├── product-service/
│   ├── cart-service/
│   ├── order-service/
│   └── payment-service/
│
├── campaign.ps1             unattended fault campaign
├── demo.ps1                 end-to-end demonstration
└── docker-compose.yml
```

---

## 🚀 Getting Started

### Clone the repository

```bash
git clone https://github.com/sarthak-jain-2006/AI-Powered-Observability-Platform.git
cd AI-Powered-Observability-Platform
```

### Start the platform

```bash
docker compose up -d --build
```

Grafana is available at `http://localhost:3000`, Prometheus at `:9090` and Jaeger at `:16686`.

### Run the end-to-end demo

```powershell
.\demo.ps1
```

This establishes a healthy baseline, injects a fault, recovers it, then reports detection, root cause and the remediation decision — all scored against the labels written during the run.

### Generate a dataset and train

```powershell
# collect fault-free traffic to learn normal behaviour
docker compose run -d --rm k6 run /scripts/baseline.js

# fit one model per service on normal traffic only
docker exec ai-engine python train.py

# cycle every fault at every severity to build the evaluation set
.\campaign.ps1 -Repetitions 1

# score both detectors against ground truth
docker exec ai-engine python detect.py --model zscore
docker exec ai-engine python detect.py --model iforest
docker exec ai-engine python remediate.py
```

---

## 📈 Planned Enhancements

- Live remediation with container restart, currently dry-run only
- Recovery verification wired into the live loop
- Comparison against published anomaly detection baselines
- Constant-load baselines to tighten the normal operating envelope
- Kubernetes deployment
- Alertmanager integration

---

## 📸 Screenshots

Add screenshots of:

- Grafana Dashboard
- Prometheus Targets
- Jaeger Traces
- Loki Logs
- Docker Containers

---

## 👨‍💻 Author

**Sarthak Jain**

- GitHub: https://github.com/sarthak-jain-2006
- LinkedIn: https://linkedin.com/in/sarthak-jain-790089302

---

## ⭐ If you found this project interesting, consider giving it a star!
