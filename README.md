# StudentAssign

Student Assignment & Submission Management System — built for an Advanced
Software Engineering practical examination.

## Quick start (local)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python seed.py          # creates the DB and demo accounts
python app.py            # runs on http://localhost:5000
```

Demo accounts (created by `seed.py`):

| Role | Email | Password |
|---|---|---|
| Instructor | instructor@demo.com | Password1 |
| Student | student1@demo.com | Password1 |
| Student | student2@demo.com | Password1 |

## Run tests

```bash
pip install pytest
pytest -v
```

## Deploy (Render)

1. Push this repo to GitHub.
2. On Render: New → Blueprint → point at this repo (uses `render.yaml`).
3. Render provisions a free PostgreSQL DB and a web service, wiring
   `DATABASE_URL` and `SECRET_KEY` automatically.
4. After the first deploy, open the Render Shell for the web service and run:
   `flask init-db` to create tables, then optionally `python seed.py` for demo data.

See `/docs` in the submission package for full project documentation,
SRS, testing report, technical debt plan, and user manual.
