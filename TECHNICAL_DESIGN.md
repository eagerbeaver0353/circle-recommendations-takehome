# Technical Design

## Problem and approach

The goal is to give members a short list of Circles worth exploring, rather than just the closest topic matches. The data is a fixed synthetic snapshot of 100 users and 40 Circles, so I chose a deterministic, rule-based approach instead of a machine learning model. It's easier to test, explain, and reproduce. The pipeline filters out Circles a member shouldn't see, scores the eligible ones using interests and activity, then diversifies the top results.

## Architecture and data

FastAPI serves the recommendation endpoint and a database readiness check. SQLAlchemy manages a normalized SQLite schema covering users, topics, Circles, interests, tags, memberships, and activity. The `python -m app.seed` command validates the committed JSON fixtures and reloads the database in a transaction. If an import fails, the transaction rolls back instead of leaving partially loaded data.

I kept ranking separate from the API layer. Pure functions handle eligibility, scoring, and diversification; the API fetches the selected Circle details and builds explanations without changing their rankings. All activity calculations use the snapshot date, September 21, 2026 UTC, rather than the current date.

## Eligibility and scoring

A Circle is excluded if the member already belongs to it, it's full, or its access is unlisted. I also exclude clearly dormant Circles, but only when all three conditions hold: zero feed posts in 30 days, no more than three chat messages, and last activity over 60 days before the snapshot. Public request-to-join Circles remain eligible.

For relevance, an exact primary-topic match scores 1.0, while a matching tag scores 0.25. Community quality combines log-normalized feed volume (55%), log-normalized chat volume (30%), and activity recency (15%). When a member has stated interests, the final base score uses 70% relevance and 30% quality. Without stated interests, I infer a weaker preference only when the member already belongs to at least two Circles sharing a primary topic; that mode uses 25% relevance and 75% quality. With no useful interest evidence, cold-start ranking uses quality alone.

## Diversity and explanations

A greedy reranker subtracts 0.10 for each previously selected Circle sharing the candidate's non-null primary topic. In the first five positions, it generally limits results to two per topic. When a different-topic candidate has positive relevance and fits the cap, the reranker defers a third repeated-topic Circle. Otherwise, a third is allowed if its base score beats the best remaining different-topic alternative by more than 0.25, or no alternative remains. Circles without a primary topic are never grouped together.

Explanations come from the same scoring evidence and stored Circle metadata. They distinguish stated from inferred interests, describe activity as snapshot evidence rather than live status, and don't imply that request-to-join means immediate admission.

## Testing and tradeoffs

Tests cover seeding and rollback, ranking rules, explanations, API validation, readiness, and the four planted scenarios. They also exercise all 100 users with limits of 1, 5, 10, and 20. Docker Compose runs the API with a persistent SQLite volume at `/app/state`; JSON fixtures remain available under `/app/data`, and seeding is explicit. I left out Postgres, queues, authentication, embeddings, and LLMs because they add complexity without improving this small, explainable assessment.
