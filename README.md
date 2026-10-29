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
- `GET /api/members` — list all (each member without `tier` or `spend`)
- `GET /api/members/:id` — get one (`404` if missing) — the stored fields plus the loyalty
  `tier` and `spend` (see below)
- `PUT /api/members/:id` — partial update
- `DELETE /api/members/:id`

### Loyalty tier on a single member

`GET /api/members/:id` adds two fields to the member payload: `tier` and `spend`. The spend comes
from `GET /api/payments/member/:memberId/spend` on gym-payments-service-python and is a JSON
number rounded to cents; the tier is derived from that rounded spend:

- `BRONZE` — spend below 100 (including 0 and negative spend)
- `SILVER` — spend from 100 up to, but not including, 500
- `GOLD` — spend of 500 or more

If the payments service times out (2 second timeout, no retries), cannot be reached, answers with
an error status or sends a body that cannot be read, the request still returns `200` with
`"tier": "UNAVAILABLE"` and `"spend": null`. The members list is unaffected.

## Tests

```
pytest
ruff check .
```
