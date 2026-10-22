# Todo Management API — Phase 1

Phase 1 is the backend only. The React frontend is intentionally out of scope.
The API uses FastAPI, Python 3.12+, SQLAlchemy 2.x async sessions, PostgreSQL,
Alembic, Pydantic v2, Argon2 password hashing, and JWT bearer authentication.

## Prerequisites

- Python 3.12 or newer.
- PostgreSQL 14 or newer, running locally or at a reachable managed endpoint.
- A PostgreSQL role permitted to create and use the application database.

Install PostgreSQL using the official packages/instructions for your operating
system at [postgresql.org/download](https://www.postgresql.org/download/).
On Windows, install the PostgreSQL server and command-line tools, start the
PostgreSQL service, and verify with `psql --version`.

If PostgreSQL is installed but stopped, open PowerShell as Administrator,
find the service name, then start it (replace the example service name with
the one shown on your machine):

```powershell
Get-Service *postgres*
Start-Service postgresql-x64-18
```

### Create the database and role

Connect as a PostgreSQL administrator using `psql`, then run the following,
replacing the example password with a unique value:

```sql
CREATE ROLE todo_user WITH LOGIN PASSWORD 'replace-this-password';
CREATE DATABASE todo_app OWNER todo_user;
```

Do not use the example password in a deployed environment.

## Python environment and configuration

The checked-in `.env.example` uses a local PostgreSQL URL and placeholder
credentials. Create `.env` only if you do not already have one, then replace
the database password and JWT secret with local values. From the repository
root in PowerShell:

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` and set:

- `DATABASE_URL`: PostgreSQL SQLAlchemy async URL, for example
  `postgresql+psycopg://todo_user:your-password@localhost:5432/todo_app`.
- `JWT_SECRET_KEY`: a random value of at least 32 characters. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `ADMIN_NAME`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`: unique credentials for
  the initial administrator. Use a password of at least 12 characters.
- `OPENROUTER_API_KEY`: needed only to use chatbot functionality.
- `OPENROUTER_MODEL` and `OPENROUTER_BASE_URL`: optionally select an OpenRouter
  model or compatible API base URL.
- `CORS_ORIGINS`: comma-separated, explicit frontend origins. Do not use `*`
  with credentials enabled.
- `ENVIRONMENT`: set to `production` in deployed environments.

The application refuses non-PostgreSQL `DATABASE_URL` values. `.env` is ignored
by Git; never place secrets in `.env.example` or source files.
The application uses SQLAlchemy's async psycopg 3 driver. It normalizes a
Neon-generated `postgresql://` URL to `postgresql+psycopg://`; preserve
Neon's TLS parameters. Use the pooled `-pooler` URL for API traffic and the
direct URL for migrations and admin seeding. Production settings require
`sslmode=require` or stronger and HTTPS CORS origins.

See the repository [Neon deployment guide](../README.md#phase-4--prepare-a-neon-backed-deployment)
for secure connection-string handling, pool sizing, branch testing, migrations,
backup/restore, hosting configuration, and troubleshooting.

## Migrations and initial administrator

Apply the Alembic migrations:

```powershell
python -m alembic upgrade head
```

Create the administrator:

```powershell
python -m scripts.seed_admin
```

The seed command is repeatable. If the configured email already belongs to an
admin, it makes no changes. It refuses to elevate a regular account and never
overwrites an existing password. For credential rotation, use a separately
authorized administrative procedure; changing `ADMIN_PASSWORD` and rerunning
the seed command intentionally does not modify an existing account.

## Run the API

```powershell
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation and
`http://127.0.0.1:8000/` for a simple server-running response.
`http://127.0.0.1:8000/health` is the liveness endpoint; use
`/health/ready` to verify database connectivity.

## Endpoints

- `GET /` — confirms the API server is running (does not check database access).
- `GET /health` — liveness check; does not check database access.
- `GET /health/ready` — readiness check; verifies database connectivity.
- `POST /api/v1/auth/register` — public registration; always creates a `user`.
- `POST /api/v1/auth/login` — accepts a JSON email/password payload.
- `GET /api/v1/auth/me` — authenticated current-user profile.
- `GET /api/v1/users` — admin-only user listing.
- `GET /api/v1/users/{user_id}` — self or admin.
- `GET /api/v1/tasks` — task listing, pagination (`page`, `size`), search, and
  status/priority filters.
- `POST /api/v1/tasks`, `GET /api/v1/tasks/{task_id}`,
  `PATCH /api/v1/tasks/{task_id}`, `DELETE /api/v1/tasks/{task_id}` — task CRUD.
- `POST /api/v1/chatbot/message` — authenticated OpenRouter-powered task
  assistant.

Regular users can only access their own tasks; admins can manage all tasks.
Task ownership is not accepted from public create/update payloads.

The chatbot uses an allowlist of validated task tools and authenticated service
operations. A delete request first asks for confirmation; the user must reply
with the exact command `confirm delete task <task_id>`. A model tool argument
cannot authorize deletion. Provider credentials remain on the server.

## Tests

Tests require a dedicated PostgreSQL database whose database name contains
`test`; they apply Alembic migrations and clear test data. Never point this
variable at a production or shared application database.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://todo_user:your-password@localhost:5432/todo_test"
python -m pytest -q tests
```

Tests deliberately use PostgreSQL, never SQLite. OpenRouter calls are mocked.
Run the command from the backend directory so the `app`, `scripts`, and
`tests` packages resolve consistently. When `TEST_DATABASE_URL` is not set,
the database-backed tests skip instead of connecting to `DATABASE_URL`.

## Deployment and security notes

The application rejects requests declaring a body larger than 1 MiB; configure
the reverse proxy/API gateway to enforce the same limit for streamed requests
and to apply per-user/IP rate limits, especially to login and chatbot endpoints.
Keep database and JWT secrets in a deployment secret manager, use HTTPS, restrict
database network access, and configure production CORS origins explicitly.
Application logs avoid recording chatbot prompts, tokens, and provider response
bodies.

## Troubleshooting

- **Database connection refused:** confirm PostgreSQL is running, the host/port
  are reachable, and `DATABASE_URL` names the intended database.
- **Windows PostgreSQL service will not start:** run PowerShell as
  Administrator, find the installed service name with `Get-Service *postgres*`,
  and start that service. If Windows reports access denied, the shell is not
  elevated.
- **Password authentication failed:** verify the PostgreSQL role/password and
  URL-encode special characters in the URL password.
- **Missing or weak JWT secret:** set `JWT_SECRET_KEY` to at least 32 characters.
- **Migration command fails:** activate the virtual environment, verify the
  database exists, and run `python -m alembic upgrade head` again.
- **Admin seed refuses an account:** it never elevates ordinary users or resets
  admin passwords; use an explicit, audited operator procedure.
- **Chatbot unavailable:** verify OpenRouter settings and connectivity; API
  errors are returned without exposing provider credentials.
- **Tests skip:** set `TEST_DATABASE_URL` to a disposable PostgreSQL database
  with `test` in its name.

## Session resumption

Before changing code in a new development session, read `AGENT_PROGRESS.md`,
then verify the actual repository state and test results. Resume the next
unfinished checklist item, update the progress log after each milestone, and
record the exact stopping point before ending a session. Never record secret
values or claim unrun tests passed.
