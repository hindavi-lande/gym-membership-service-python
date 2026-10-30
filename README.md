# gym-membership-service-python

Python/Flask baseline for a fitness/gym membership domain: a single `Member` resource with full
CRUD, mirroring `gym-membership-service` (Express) so the same tickets can be exercised against a
Python stack.

## Domain model

- **Member** — firstName, lastName, email (unique, required), phone (optional), membershipPlan
  (`BASIC` / `STANDARD` / `PREMIUM`, defaults to `BASIC`), status (`ACTIVE` / `INACTIVE` /
  `SUSPENDED`, defaults to `ACTIVE`), joinedAt (defaults to today)

## Stack

- Flask 3 with an application factory and one blueprint per resource
- Flask-SQLAlchemy 3 / SQLAlchemy 2, SQLite for local dev
- pytest + Flask test client; ruff for linting

## Project structure

```
app/
  __init__.py        # create_app factory, blueprint and error-handler wiring
  config.py          # environment-backed config
  extensions.py      # SQLAlchemy instance
  errors.py          # ApiError and JSON error handlers
  models/            # SQLAlchemy models
  services/          # business logic, DB access
  clients/           # calls to gym-payments-service-python
  routes/            # Flask blueprints
tests/               # pytest suite
wsgi.py              # WSGI entrypoint
```

## Run

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask run
```

`flask run` reads `.flaskenv` and listens on `http://localhost:3000`. The SQLite file is created at
`data/dev.sqlite` on first run. Set `DATABASE_URL` to point elsewhere (for example Postgres) and
`FLASK_RUN_PORT` to change the port.

## Endpoints

- `GET /api/health` — liveness check
- `POST /api/members` — `{ "firstName", "lastName", "email", "phone", "membershipPlan" }` —
  firstName, lastName, email required; email must be unique
- `GET /api/members` — list all
- `GET /api/members/:id` — get one (`404` if missing)
- `PUT /api/members/:id` — partial update
- `POST /api/members/:id/cancel` — cancels the membership, refunding the unused part of the paid
  period (`plan price * remainingDays / 30`) through the payments service
- `DELETE /api/members/:id`
## Tests

```
pytest
ruff check .
```
