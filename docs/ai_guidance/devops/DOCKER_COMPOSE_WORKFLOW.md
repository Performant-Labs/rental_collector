# Docker Compose Workflow

This project uses container-first local development.

## Policy
- Development services should run in one or two containers where practical.
- Avoid host-level dependency installs for dashboard runtime/testing.
- Run dashboard tests inside the `dashboard-api` container.

## Standard Services
- `dashboard-api`
- `meilisearch`

## Standard Commands
- Start services:
  - `docker compose up -d dashboard-api meilisearch`
- Run dashboard tests:
  - `docker compose run --rm dashboard-api python -m pytest dashboard/tests -v`
- View logs:
  - `docker compose logs -f dashboard-api`
- Stop stack:
  - `docker compose down`

## Container Conventions
- Use bind mounts for local development iteration.
- Keep working directory consistent (e.g. `/app`).
- Avoid ad-hoc divergence between Dockerfile and compose command paths.

## Reliability
- Health endpoint required (`/health`) for service checks.
- Non-destructive commands should be safe to auto-run in agent workflows.

## Secrets and Env
- Keep secrets out of `docker-compose.yml` when possible.
- Use environment variables or `.env` (gitignored) for sensitive values.
