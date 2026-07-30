# AI-Powered Observability Platform

An AI-driven observability platform built on a microservices-based e-commerce application. The project combines distributed systems, modern observability tools, configurable fault injection, and an AI telemetry pipeline to collect operational data for anomaly detection and root cause analysis.

---

## 🚀 Features

- Microservices-based e-commerce application
- Dockerized deployment using Docker Compose
- Distributed tracing with OpenTelemetry and Jaeger
- Metrics collection using Prometheus
- Interactive dashboards with Grafana
- Centralized logging with Loki
- Configurable fault injection for resilience testing
- AI telemetry pipeline for dataset generation
- REST APIs with validation and global error handling

---

## 🏗️ Architecture

```
                        +----------------------+
                        |      Grafana        |
                        +----------+----------+
                                   |
          +------------------------+------------------------+
          |                        |                        |
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
          |  User Service                                   |
          |  Product Service                                |
          |  Cart Service                                   |
          |  Order Service                                  |
          |  Payment Service                                |
          +-------------------------------------------------+
                             |
                             |
                      AI Telemetry Engine
```

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

The platform continuously collects telemetry from all microservices, including:

- CPU Usage
- Memory Usage
- Request Latency
- Request Count
- Error Rate
- Service Availability
- Payment Failures
- Order Failures

Telemetry snapshots are collected periodically and stored to build datasets for future machine learning models focused on:

- Anomaly Detection
- Root Cause Analysis
- Failure Prediction

---

## ⚠️ Fault Injection

The platform supports configurable fault injection without changing application code.

Examples include:

- Payment failures
- Artificial request delays
- Increased response latency
- High error rates
- Service failures

These faults are configurable using environment variables.

Example:

```env
PAYMENT_FAILURE_RATE=0.3
PAYMENT_DELAY_MS=5000
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

### DevOps

- Docker
- Docker Compose

---

## 📁 Project Structure

```
AI-Powered-Observability-Platform
│
├── ai-engine/
├── faults/
├── load/
├── observability/
├── services/
│   ├── user-service/
│   ├── product-service/
│   ├── cart-service/
│   ├── order-service/
│   └── payment-service/
│
├── docker-compose.yml
└── README.md
```

---

## 🚀 Getting Started

### Clone the repository

```bash
git clone https://github.com/sarthak-jain-2006/AI-Powered-Observability-Platform.git
```

### Navigate to the project

```bash
cd AI-Powered-Observability-Platform
```

### Configure environment variables

Create `.env` files for each service as required.

### Start the platform

```bash
docker compose up --build
```

---

## 📈 Planned Enhancements

- AI-based anomaly detection
- Root cause analysis using machine learning
- Automatic incident detection
- Predictive failure analysis
- Self-healing recommendations
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
