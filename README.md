# Seed dataset — Recommend Circles to Join

This folder is the dataset for the take-home. It's a small, **fully synthetic** snapshot
of a Lean In Connect–style community: members, Circles, who belongs to which Circle,
the topic taxonomy, and recent Circle feed activity.

Everything here is generated (`generate.mjs`) — no real people, no real content.

## Files

| File | Rows | What it is |
| --- | --- | --- |
| `data/topics.json` | 22 | The topic taxonomy Circles and members are tagged with |
| `data/users.json` | 100 | Members: profile fields + stated topic interests |
| `data/circles.json` | 40 | Circles: profile, topic, capacity, and activity aggregates |
| `data/memberships.json` | ~440 | Who belongs to which Circle, and their role |
| `data/activity.json` | ~390 | Recent Circle feed posts with engagement counts |

## Loading it

The data is plain JSON so it drops into anything — Postgres, SQLite, or just an
in-memory array. Load it however suits your design; you don't have to mirror our shapes.

```js
const users = JSON.parse(fs.readFileSync("data/users.json", "utf8"));
```

## Data dictionary

### `topics.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `slug` | string | kebab-case, e.g. `negotiation` |
| `label` | string | display name |
| `domain` | string | always `content` here |

### `users.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `first_name`, `last_name` | string | synthetic |
| `has_photo` | bool | whether a profile photo is set |
| `bio` | string \| null | |
| `job_title` | string \| null | |
| `company` | string \| null | |
| `industry` | string \| null | |
| `location` | string \| null | |
| `joined_at` | ISO datetime | account age / tenure signal |
| `topic_interests` | string[] | topic slugs the member selected; **may be empty** |
| `profile_completeness` | number 0–1 | share of {photo, bio, job title, company-or-industry, location} present |

### `circles.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `name`, `slug`, `description` | string / null | `description` and `cover_image_url` may be null |
| `topic` | string \| null | topic slug; **some Circles have no topic** |
| `tags` | string[] | free-form topic-ish tags |
| `cover_image_url` | string \| null | |
| `format` | enum | `in_person` \| `virtual` \| `hybrid` |
| `access` | enum | `public` \| `unlisted` |
| `join_policy` | enum | `open` \| `request` |
| `max_members` | int \| null | capacity; **null means uncapped** |
| `member_count` | int | current members |
| `created_at` | ISO datetime | |
| `last_activity_at` | ISO datetime | timestamp of the most recent activity |
| `feed_posts_30d` | int | posts in the last 30 days |
| `chat_messages_30d` | int | group-chat message volume in the last 30 days (aggregate count only) |

### `memberships.json`
| field | type | notes |
| --- | --- | --- |
| `user_id` | int | → `users.id` |
| `circle_id` | int | → `circles.id` |
| `role` | enum | `member` \| `leader` (a Circle's leaders are just members with `role=leader`) |
| `joined_at` | ISO datetime | |

### `activity.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `circle_id` | int | → `circles.id` |
| `author_user_id` | int | → `users.id` (always a member of that Circle) |
| `body` | string | post text |
| `reaction_count`, `comment_count`, `save_count` | int | engagement on the post |
| `created_at` | ISO datetime | |

## A few things are intentionally *derived*, not stored

Mirroring the real product, some signals aren't handed to you as a column — you decide
how to compute them:

- **Is a Circle full?** Compare `member_count` to `max_members` (and `max_members` can be null).
- **How active is a Circle?** Combine `feed_posts_30d`, `last_activity_at`, `chat_messages_30d`,
  and engagement in `activity.json` however you think best.
- **A Circle's leaders and their profiles** come from `memberships` (`role=leader`) joined to `users`.

## What we deliberately did *not* include

- **Embeddings / precomputed similarity.** Topic overlap and the fields above are enough for this exercise.
- **Raw group-chat message text.** Only the aggregate `chat_messages_30d` count, for privacy realism.

## Named records for the scenarios

The assignment says we'll run your submission against planted records. Here they are —
build so these return sensible results, and be ready to talk through them:

| Scenario | Run for | What's planted |
| --- | --- | --- |
| **Cold start** | `user_id 42` | No memberships, no stated interests, empty profile (`profile_completeness = 0`) |
| **Obvious matches** | `user_id 7` | Interests `leadership-skills`, `public-speaking`; strong active/open Circles exist for both (`#5 Women Who Lead`, `#6 Speak Up Circle`) that she hasn't joined |
| **Duplicate Circles** | `user_id 15` | Interest `negotiation`; Circles `#10`, `#11`, `#12` are three near-identical active Negotiation Circles — a good list shouldn't return all three |
| **Full / inactive** | `user_id 23` | Interest `getting-promoted`; `#20 The Promotion Path` is **full** (at capacity) and `#21 Career Climbers` is **inactive** (no posts in ~7 months) — both look like great topic matches but shouldn't rank; `#22 Level Up Collective` is the healthy alternative |

Regenerate the data anytime with `node generate.mjs` (it's deterministic — same output every run).
