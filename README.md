# Lean In Circle Recommendations

Personalized Circle recommendations for Lean In Connect–style members. The API
ranks Circles a member has not joined, using topic interests and Circle activity
from a fixed synthetic snapshot, and returns short evidence-based explanations
so each suggestion is understandable without inventing live-platform claims.

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2
- SQLite
- Pydantic v2
- pytest
- Ruff
- Docker and Docker Compose

## Quick start — Docker

From a fresh checkout:

```bash
docker compose build
docker compose run --rm api python -m app.seed
docker compose up -d
```

Seeding is explicit and idempotent: it creates (or replaces) seed-managed rows
in a persistent Docker volume. The API does not seed on image build or container
start. The SQLite file lives at `/app/state/circles.db` inside the `circles-state`
volume so JSON fixtures under `/app/data` remain available to the seed command.

Verify:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/v1/users/23/circle-recommendations?limit=5"
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Stop the service (keeps the volume):

```bash
docker compose down
```

Optional and destructive — remove the persistent database volume:

```bash
docker compose down -v
```

## Local Python development

Requires Python 3.12+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

Local default database URL: `sqlite:///./data/circles.db` (override with
`CIRCLES_DATABASE_URL`). Seed and API must use the same URL.

## API documentation

### `GET /api/v1/users/{user_id}/circle-recommendations`

| Parameter | Notes |
| --- | --- |
| `user_id` | Positive integer path parameter |
| `limit` | Query parameter, default `5`, allowed range `1`–`20` |

Response shape:

```json
{
  "user_id": 23,
  "recommendations": [
    {
      "rank": 1,
      "circle_id": 22,
      "slug": "level-up-collective",
      "name": "Level Up Collective",
      "description": "A supportive circle for women focused on getting promoted.",
      "topic": "getting-promoted",
      "format": "hybrid",
      "join_policy": "request",
      "cover_image_url": "https://images.example.org/circles/level-up-collective.jpg",
      "reason": "This Circle matches your interest in getting promoted and had recent member activity in the available snapshot."
    }
  ]
}
```

Behavior:

- Unknown `user_id` → `404` with `{"detail":"User not found"}`
- Invalid `user_id` or `limit` → `422`
- Eligible list shorter than `limit` → returns whatever remains (may be empty)

### Other endpoints

| Path | Purpose |
| --- | --- |
| `GET /health` | Readiness: `200` when the DB is schematized and minimally seeded; `503` otherwise |
| `GET /docs` | Swagger UI |
| `GET /openapi.json` | OpenAPI schema |

## How recommendations work

1. **Eligibility** — drop Circles the member already joined, Circles at capacity,
   unlisted Circles, and clearly dormant Circles.
2. **Interest matching** — use explicit topic interests when present; otherwise
   infer from memberships when enough history exists; otherwise cold-start.
3. **Activity quality** — blend feed volume, chat volume, and recency against the
   fixed September 21, 2026 snapshot.
4. **Confidence-aware scoring** — weight topic relevance vs activity quality by
   personalization mode (explicit / inferred / cold start).
5. **Diversity reranking** — greedy selection with a same-topic penalty and a
   relevance-aware first-five topic cap.
6. **Explanations** — deterministic sentences grounded in ranking evidence only.

Details: [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md).

## Tests

```bash
ruff check app tests
pytest -v
```

Coverage includes the four planted scenarios (users 7, 15, 23, and 42) and
recommendation requests for all 100 seeded users at limits 1, 5, 10, and 20.
Tests run in the local Python environment (the runtime image does not ship the
`tests/` package).

## Data

Synthetic fixtures live in `data/*.json` and are loaded by `python -m app.seed`.
Field definitions, provenance, planted scenarios, and `generate.mjs` notes are in
[DATASET.md](DATASET.md).

Do not commit a generated SQLite database. JSON fixtures are source data; the
database is created by seeding.

## Assumptions and limitations

- Data is synthetic and snapshot-based (reference date: 2026-09-21 UTC).
- No external LLM, embeddings, or vector database is required.
- Ranking uses topic and activity signals only; Circles have no geography field.
- Cold-start users receive quality-based community recommendations without
  invented personalization.
- Explanations describe snapshot evidence, not live platform activity.
- Circles with `join_policy=request` remain eligible but require approval to join.
