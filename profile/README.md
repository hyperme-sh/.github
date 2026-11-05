# hyperme.sh

**Hypermesh** — lease AI compute on certified hosts.

Renters run Full Model and timed leases against hardware hosts that pass certification. Hosts get paid for capacity they put on the network. Agents and people use the same product nouns.

## Product

- **Site:** [hyperme.sh](https://hyperme.sh)
- **Full Model** and **time leases** — live
- **Your Model** — coming soon
- **Visor** uses Hypermesh models at release

## This organization

Open-source repositories for Hypermesh clients, hosts, and the control plane that places leases on certified hosts.

Company: [Fyber Labs](https://fyberlabs.com).

Private product documentation stays in `hypermesh-docs`. Public operator documentation, plane templates, and deployment configuration live in [spanopticon](https://github.com/hyperme-sh/spanopticon).

## Public repositories

### Product clients and host

- **[hypermesh-host](https://github.com/hyperme-sh/hypermesh-host)** — Host installer and agent for certified machines (Jetson AGX Orin and Orin NX first): enrollment, heartbeats, WireGuard, and the inference jobs the control plane assigns.
- **[hypermesh-cli](https://github.com/hyperme-sh/hypermesh-cli)** — Thin CLI (`hypermesh` and `hm`) to browse the catalog, check out a lease, chat on the router, and manage local MCP config.
- **[hypermesh-visor](https://github.com/hyperme-sh/hypermesh-visor)** — Linux desktop daemon for a live session: view, watch, listen, mouse, and type.
- **[hypermesh-vscode](https://github.com/hyperme-sh/hypermesh-vscode)** — VS Code extension that sends one short completion to a configured Hypermesh chat host.
- **[hypermesh-conductor](https://github.com/hyperme-sh/hypermesh-conductor)** — Design for a budgeted, recoverable task runtime (model and host selection, token and time budgets). The repository holds that design; there is no package yet.
- **[hypermesh-bench](https://github.com/hyperme-sh/hypermesh-bench)** — Model and harness soak for host certification: recipes, scorecards, and an AGX Orin batch runner that hosts pull and run.

### Hypermesh plane

- **[hypermesh-gateway](https://github.com/hyperme-sh/hypermesh-gateway)** — Ticket-authorized chat routing and WireGuard gateway. It validates lease tickets and proxies authorized chat to the assigned host.
- **[hypermesh-ticket](https://github.com/hyperme-sh/hypermesh-ticket)** — Lease-ticket signing and verification (`hm1` wire format) used by the gateway.
- **[hypermesh-pricing](https://github.com/hyperme-sh/hypermesh-pricing)** — Stateless pricing engine: clearing rules (floor, base price, order book, day-ahead) and an internal HTTP service. Shipped tuning values are simulated defaults.

### Control-plane libraries and services

- **[controlplane-api](https://github.com/hyperme-sh/controlplane-api)** — Shared settings, logging, HTTP scaffolding, health and version endpoints, permissions, and operator plugin registration.
- **[controlplane-core](https://github.com/hyperme-sh/controlplane-core)** — Shared API compatibility layer that aliases the installed API, identity, and tenancy packages.
- **[controlplane-db](https://github.com/hyperme-sh/controlplane-db)** — SQLAlchemy models, database sessions, store interfaces, and Alembic migration resources.
- **[controlplane-identity](https://github.com/hyperme-sh/controlplane-identity)** — Token comparison, API-key and Keycloak validation, purpose-bound sessions, and Base wallet proof verification.
- **[controlplane-tenancy](https://github.com/hyperme-sh/controlplane-tenancy)** — Database-session tenant context, membership helpers, and marketplace tenant configuration.
- **[controlplane-events](https://github.com/hyperme-sh/controlplane-events)** — Typed event envelopes, JSON schemas, validation, publishing, and event-store helpers.
- **[controlplane-models](https://github.com/hyperme-sh/controlplane-models)** — Shared Pydantic domain contracts (`spanopticon-models`), with optional gRPC adapters.
- **[controlplane-edge](https://github.com/hyperme-sh/controlplane-edge)** — HTTP edge proxy with OpenAPI aggregation, GraphQL, and optional ContractEcho gRPC.
- **[controlplane-sdk](https://github.com/hyperme-sh/controlplane-sdk)** — Generated REST clients, protocol snapshots, and auth examples. The installable wheel is the Python client.
- **[controlplane-proto](https://github.com/hyperme-sh/controlplane-proto)** — Python package for the `spanopticon.v1` ContractEcho protocol buffers.
- **[controlplane-keycloak](https://github.com/hyperme-sh/controlplane-keycloak)** — Keycloak realm configuration and reconciliation helpers for control-plane clients and identity brokers.
- **[controlplane-tests](https://github.com/hyperme-sh/controlplane-tests)** — Test helpers for PostgreSQL migration templates, database URL conversion, and schema comparison (`spanopticon-tests`).
- **[auth-service](https://github.com/hyperme-sh/auth-service)** — Authentication HTTP service and reusable auth dependency interfaces.
- **[user-service](https://github.com/hyperme-sh/user-service)** — User and operator-account service, plus a read-only operator-ban contract.
- **[acl-service](https://github.com/hyperme-sh/acl-service)** — Tenant authorization: Casbin policies and SociACL witness and keyring interfaces.
- **[api-keys-service](https://github.com/hyperme-sh/api-keys-service)** — API key creation, listing, and revocation, with purpose restrictions and secret hashing.

### Plane docs and templates

- **[spanopticon](https://github.com/hyperme-sh/spanopticon)** — Public documentation and deployment templates for service planes. It generates Compose and Kubernetes manifests from an image digest you supply.

### Organization profile

- **[.github](https://github.com/hyperme-sh/.github)** — This organization profile.
