// Synthetic seed-data generator for the "Recommend Circles" take-home.
//
// Standalone, dependency-free, deterministic (fixed PRNG seed) so the dataset is
// byte-stable and every candidate is scored against identical records.
//
// Deliberately NOT wired into the app's real seed pipeline:
//   - candidates must not receive our production schema (they design their own)
//   - the data goes onto strangers' machines, so every record is fully synthetic
//   - flat JSON loads into any DB or just into memory, in any language
//
// Vocabulary (topic slugs/labels, role values, field names) mirrors the real
// Lean In Connect domain so the fixture feels authentic.
//
//   Run:  node generate.mjs
//   Out:  ./data/{topics,users,circles,memberships,activity}.json

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = join(HERE, "data");

// ---- deterministic PRNG (mulberry32) ---------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(20260921);
const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
const int = (lo, hi) => lo + Math.floor(rnd() * (hi - lo + 1));
const chance = (p) => rnd() < p;
function sampleUnique(arr, k) {
  const copy = [...arr];
  const out = [];
  while (out.length < k && copy.length) out.push(copy.splice(Math.floor(rnd() * copy.length), 1)[0]);
  return out;
}
const round2 = (n) => Math.round(n * 100) / 100;
const ANCHOR = Date.parse("2026-09-21T00:00:00Z");
const daysAgo = (d) => new Date(ANCHOR - Math.round(d * 86400000)).toISOString();

// ---- taxonomy (canonical `content` domain slugs) ---------------------------
const TOPICS = [
  ["leadership-skills", "Leadership skills"],
  ["managing-a-team", "Managing a team"],
  ["giving-feedback", "Giving feedback"],
  ["negotiation", "Negotiation"],
  ["getting-promoted", "Getting promoted"],
  ["managing-up", "Managing up"],
  ["visibility-recognition", "Visibility & recognition"],
  ["networking", "Networking"],
  ["sponsorship-mentorship", "Sponsorship & mentorship"],
  ["confidence", "Confidence"],
  ["imposter-syndrome", "Imposter syndrome"],
  ["stress-burnout", "Stress & burnout"],
  ["resilience", "Resilience"],
  ["communication", "Communication"],
  ["difficult-conversations", "Difficult conversations"],
  ["gender-bias", "Gender bias"],
  ["allyship", "Allyship"],
  ["working-motherhood", "Working motherhood"],
  ["public-speaking", "Public speaking"],
  ["career-breaks", "Career breaks"],
  ["work-life-integration", "Work-life integration"],
  ["being-the-only-one", "Being the only one"],
].map(([slug, label], i) => ({ id: i + 1, slug, label, domain: "content" }));
const TOPIC_SLUGS = TOPICS.map((t) => t.slug);

// ---- people vocabulary -----------------------------------------------------
const FIRST_NAMES = [
  "Amara","Priya","Sofia","Lena","Naomi","Yuki","Mei","Fatima","Zoe","Isabel","Aisha","Nadia",
  "Grace","Elena","Rosa","Hana","Leila","Maya","Nina","Tara","Bianca","Carmen","Dalia","Esther",
  "Farrah","Gita","Halle","Imani","Jada","Kira","Lucia","Marisol","Noor","Olga","Paloma","Renata",
  "Simone","Thea","Uma","Valeria","Wren","Ximena","Yara","Zainab","Anika","Blythe","Camila","Devi",
  "Ingrid","Talia",
];
const LAST_NAMES = [
  "Okafor","Sharma","Reyes","Novak","Cohen","Tanaka","Chen","Haddad","Bennett","Cruz","Diallo",
  "Petrova","Ellis","Vargas","Santos","Kim","Nasser","Flores","Weaver","Malik","Rossi","Mbeki",
  "Andersson","Park","Costa","Jensen","Adeyemi","Ibrahim","Watanabe","Sokolov","Delgado","Fischer",
  "Nguyen","Obrien","Kaur","Larsson","Mendez","Osei","Romano","Vega",
];
const JOB_TITLES = [
  "Product Manager","Software Engineer","Marketing Lead","Operations Manager","UX Designer",
  "Data Analyst","Founder","Nonprofit Director","Sales Manager","HR Business Partner","Consultant",
  "Research Scientist","Attorney","Finance Manager","Program Coordinator","Engineering Manager",
  "Account Executive","Recruiter","Strategy Lead","Community Manager",
];
const COMPANIES = [
  "Northwind","Acme Health","Brightwave","Cedar & Co","Meridian Labs","Kestrel","Lumen","Vantage",
  "Harbor Financial","Willow Education", null, null,
];
const INDUSTRIES = [
  "Technology","Healthcare","Finance","Education","Nonprofit","Retail","Media","Manufacturing",
];
const LOCATIONS = [
  "New York, NY","Chicago, IL","Austin, TX","Seattle, WA","Atlanta, GA","Denver, CO","Boston, MA",
  "Toronto, ON","London, UK","Remote",
];
const BIOS = [
  "Building my leadership toolkit one conversation at a time.",
  "First-time manager figuring it out alongside a great team.",
  "Career changer, ex-consultant, now in tech.",
  "Passionate about mentoring the next generation of women leaders.",
  "Returning to work after a career break and finding my footing.",
  "Advocate for pay equity and transparent promotion paths.",
];

// ---- circle roster (id order = 1..40, planted ids fixed) -------------------
// health: active | moderate | inactive | full
const CIRCLES_SPEC = [
  { name: "The Elevation Circle", topic: "leadership-skills", health: "active", size: "large" },
  { name: "Next Chapter Circle", topic: "career-breaks", health: "moderate", size: "medium" },
  { name: "The Balance Collective", topic: "work-life-integration", health: "active", size: "medium" },
  { name: "Women in Transition", topic: "resilience", health: "moderate", size: "medium" },
  { name: "Women Who Lead", topic: "leadership-skills", health: "active", size: "large" }, // id5: obvious match A
  { name: "Speak Up Circle", topic: "public-speaking", health: "active", size: "medium" }, // id6: obvious match B
  { name: "The Feedback Room", topic: "giving-feedback", health: "moderate", size: "small" },
  { name: "Managing Up Guild", topic: "managing-up", health: "active", size: "medium" },
  { name: "Seen & Heard", topic: "visibility-recognition", health: "moderate", size: "small" },
  { name: "Negotiation Circle", topic: "negotiation", health: "active", size: "medium" }, // id10: dup A
  { name: "The Negotiation Table", topic: "negotiation", health: "active", size: "medium" }, // id11: dup B
  { name: "Negotiate Like a Leader", topic: "negotiation", health: "active", size: "medium" }, // id12: dup C
  { name: "Confident Voices", topic: "confidence", health: "active", size: "medium" },
  { name: "Beyond Imposter Syndrome", topic: "imposter-syndrome", health: "moderate", size: "small" },
  { name: "The Network Effect", topic: "networking", health: "active", size: "large" },
  { name: "Mentors & Sponsors", topic: "sponsorship-mentorship", health: "moderate", size: "medium" },
  { name: "Hard Conversations Circle", topic: "difficult-conversations", health: "moderate", size: "small" },
  { name: "The Only One", topic: "being-the-only-one", health: "moderate", size: "small" },
  { name: "Working Mothers United", topic: "working-motherhood", health: "active", size: "medium" },
  { name: "The Promotion Path", topic: "getting-promoted", health: "full", size: "medium" }, // id20: full trap
  { name: "Career Climbers", topic: "getting-promoted", health: "inactive", size: "small" }, // id21: inactive trap
  { name: "Level Up Collective", topic: "getting-promoted", health: "active", size: "medium" }, // id22: correct answer
  { name: "Allies at Work", topic: "allyship", health: "moderate", size: "medium" },
  { name: "Burnout to Balance", topic: "stress-burnout", health: "active", size: "medium" },
  { name: "Clear Communicators", topic: "communication", health: "moderate", size: "small" },
  { name: "Naming the Bias", topic: "gender-bias", health: "moderate", size: "small" },
  { name: "Women of the 405", topic: null, health: "active", size: "medium" }, // null topic on purpose
  { name: "The Latina Coalition", topic: null, health: "moderate", size: "medium" }, // null topic on purpose
  { name: "Professionals Who Parent", topic: "working-motherhood", health: "moderate", size: "medium" },
  { name: "Early Career Collective", topic: "confidence", health: "active", size: "large" },
  { name: "Team Leads Circle", topic: "managing-a-team", health: "active", size: "medium" },
  { name: "The Resilience Room", topic: "resilience", health: "inactive", size: "small" }, // second inactive
  { name: "Return & Rise", topic: "career-breaks", health: "moderate", size: "small" },
  { name: "Visibility Lab", topic: "visibility-recognition", health: "moderate", size: "small" },
  { name: "Board-Ready Women", topic: "leadership-skills", health: "moderate", size: "medium" },
  { name: "First 90 Days", topic: "managing-a-team", health: "moderate", size: "small" },
  { name: "The Confidence Lab", topic: "confidence", health: "moderate", size: "small" },
  { name: "Speak With Impact", topic: "public-speaking", health: "moderate", size: "small" },
  { name: "Mentorship Matters", topic: "sponsorship-mentorship", health: "active", size: "medium" },
  { name: "Network & Grow", topic: "networking", health: "moderate", size: "medium" },
];

const POST_BODIES = [
  "Sharing a small win — I asked for the stretch project in my 1:1 and got it.",
  "Prepping for a comp conversation next week. Any scripts that worked for you?",
  "How do you handle being talked over in meetings? Looking for tactics that stick.",
  "Just wrapped my first performance review as a manager. Nerve-wracking but good.",
  "Reminder that saying no to one thing is saying yes to another. Protecting my calendar.",
  "Reading 'Lean In' again with fresh eyes now that I'm leading a team.",
  "Anyone else navigating a return after leave? Would love to compare notes.",
  "Got the promotion! Grateful for the practice interviews from this group.",
  "What's one boundary you set this quarter that actually held?",
  "Presenting to the exec team on Thursday — doing a practice run this week.",
  "Feedback I got that changed how I lead: be specific, be kind, be timely.",
  "Networking felt transactional to me until I started leading with curiosity.",
  "Struggling with imposter feelings on a new project. How do you reframe it?",
  "We hit our team goal and I made sure everyone got named in the recap. Visibility matters.",
  "Trying a no-meeting Friday experiment. Report back next week.",
];

// ---- users -----------------------------------------------------------------
const N_USERS = 100;
const RESERVED = { OBVIOUS: 7, DUP: 15, FULL_TRAP: 23, COLDSTART: 42 };

function completeness(u) {
  const pts =
    (u.has_photo ? 1 : 0) +
    (u.bio ? 1 : 0) +
    (u.job_title ? 1 : 0) +
    (u.company || u.industry ? 1 : 0) +
    (u.location ? 1 : 0);
  return round2(pts / 5);
}

function makeUser(id) {
  const first = FIRST_NAMES[(id * 7) % FIRST_NAMES.length];
  const last = LAST_NAMES[(id * 13) % LAST_NAMES.length];
  const base = {
    id,
    first_name: first,
    last_name: last,
    has_photo: chance(0.7),
    bio: chance(0.45) ? pick(BIOS) : null,
    job_title: chance(0.75) ? pick(JOB_TITLES) : null,
    company: chance(0.6) ? pick(COMPANIES) : null,
    industry: chance(0.7) ? pick(INDUSTRIES) : null,
    location: chance(0.7) ? pick(LOCATIONS) : null,
    joined_at: daysAgo(int(5, 720)),
    topic_interests: chance(0.25) ? [] : sampleUnique(TOPIC_SLUGS, int(1, 3)),
  };
  base.profile_completeness = completeness(base);
  return base;
}

const users = [];
for (let id = 1; id <= N_USERS; id++) users.push(makeUser(id));

// planted overrides
const byId = (id) => users[id - 1];
Object.assign(byId(RESERVED.OBVIOUS), {
  first_name: "Priya", last_name: "Sharma", has_photo: true,
  bio: "Senior IC eyeing my first leadership role. Working on executive presence.",
  job_title: "Software Engineer", company: "Meridian Labs", industry: "Technology",
  location: "Seattle, WA", topic_interests: ["leadership-skills", "public-speaking"],
});
Object.assign(byId(RESERVED.DUP), {
  first_name: "Nadia", last_name: "Haddad", has_photo: true,
  bio: "Prepping for a big comp conversation and want to build confidence around it.",
  job_title: "Account Executive", company: "Vantage", industry: "Technology",
  location: "Chicago, IL", topic_interests: ["negotiation", "confidence"],
});
Object.assign(byId(RESERVED.FULL_TRAP), {
  first_name: "Grace", last_name: "Bennett", has_photo: true,
  bio: "Been in-role two years and ready for the next level.",
  job_title: "Marketing Lead", company: "Brightwave", industry: "Media",
  location: "Atlanta, GA", topic_interests: ["getting-promoted"],
});
Object.assign(byId(RESERVED.COLDSTART), {
  first_name: "Zoe", last_name: "Ellis", has_photo: false, bio: null, job_title: null,
  company: null, industry: null, location: null, joined_at: daysAgo(1), topic_interests: [],
});
for (const id of Object.values(RESERVED)) byId(id).profile_completeness = completeness(byId(id));

// ---- circles + memberships + activity --------------------------------------
// Lean In Circles are small peer groups by design, not large communities.
const SIZE_RANGES = { small: [3, 8], medium: [9, 15], large: [16, 28] };
const slugify = (s) =>
  s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

const circles = [];
const memberships = [];
const activity = [];
let postId = 1;

// Planted users are kept out of auto-sampling entirely and given only their
// scripted memberships below, so each scenario stays legible.
const RESERVED_IDS = new Set(Object.values(RESERVED));

function healthNumbers(health) {
  switch (health) {
    case "active":
      return { posts30: int(8, 20), chat30: int(40, 220), lastAct: round2(rnd() * 5), older: int(2, 5) };
    case "moderate":
      return { posts30: int(2, 6), chat30: int(8, 40), lastAct: int(3, 20), older: int(0, 3) };
    case "inactive":
      return { posts30: 0, chat30: int(0, 3), lastAct: int(150, 250), older: int(0, 2) };
    case "full":
      return { posts30: int(6, 16), chat30: int(30, 160), lastAct: round2(rnd() * 6), older: int(1, 4) };
    default:
      return { posts30: 0, chat30: 0, lastAct: 300, older: 0 };
  }
}

// pre-pick a leader per circle, spreading leadership across the (non-planted) user base
const leaderCandidates = users.map((u) => u.id).filter((uid) => !RESERVED_IDS.has(uid));
const leaderPool = sampleUnique(leaderCandidates, Math.min(leaderCandidates.length, CIRCLES_SPEC.length + 5));

CIRCLES_SPEC.forEach((spec, idx) => {
  const id = idx + 1;
  const [lo, hi] = SIZE_RANGES[spec.size];
  let targetSize = int(lo, hi);
  const nums = healthNumbers(spec.health);

  // choose members, biased toward users interested in the circle topic
  const eligible = users.map((u) => u.id).filter((uid) => !RESERVED_IDS.has(uid));
  const weighted = [];
  for (const uid of eligible) {
    const interested = spec.topic && byId(uid).topic_interests.includes(spec.topic);
    weighted.push(uid);
    if (interested) weighted.push(uid, uid); // 3x weight
  }
  const memberIds = new Set();
  const leader = leaderPool[idx % leaderPool.length];
  memberIds.add(leader);
  let guard = 0;
  while (memberIds.size < targetSize && guard < 5000) {
    memberIds.add(pick(weighted));
    guard++;
  }
  const memberList = [...memberIds];
  const memberCount = memberList.length;

  // capacity: full circle is capped exactly at its size; others mostly capped with slack, some uncapped
  let maxMembers;
  if (spec.health === "full") maxMembers = memberCount;
  else if (chance(0.4)) maxMembers = null;
  else maxMembers = memberCount + int(2, 12);

  circles.push({
    id,
    name: spec.name,
    slug: slugify(spec.name),
    description:
      spec.topic
        ? `A supportive circle for women focused on ${TOPICS.find((t) => t.slug === spec.topic).label.toLowerCase()}.`
        : (chance(0.5) ? "A community circle for women growing their careers together." : null),
    topic: spec.topic,
    tags: spec.topic ? sampleUnique([spec.topic, ...sampleUnique(TOPIC_SLUGS, 2)], int(1, 3)) : [],
    cover_image_url: chance(0.8) ? `https://images.example.org/circles/${slugify(spec.name)}.jpg` : null,
    format: pick(["in_person", "virtual", "hybrid"]),
    access: chance(0.85) ? "public" : "unlisted",
    join_policy: chance(0.75) ? "open" : "request",
    max_members: maxMembers,
    member_count: memberCount,
    created_at: daysAgo(int(30, 900)),
    last_activity_at: daysAgo(nums.lastAct),
    feed_posts_30d: nums.posts30,
    chat_messages_30d: nums.chat30,
  });

  // memberships rows
  for (const uid of memberList) {
    memberships.push({ user_id: uid, circle_id: id, role: uid === leader ? "leader" : "member", joined_at: daysAgo(int(1, 600)) });
  }

  // activity rows (recent + a few older); authors drawn from members
  const authors = memberList.length ? memberList : [leader];
  const engScale = spec.health === "active" || spec.health === "full" ? 1 : 0.35;
  const emit = (dayLo, dayHi, count) => {
    for (let k = 0; k < count; k++) {
      const reactions = Math.round(int(0, 18) * engScale);
      activity.push({
        id: postId++,
        circle_id: id,
        author_user_id: pick(authors),
        body: pick(POST_BODIES),
        reaction_count: reactions,
        comment_count: Math.round(reactions * (0.3 + rnd() * 0.5)),
        save_count: Math.round(reactions * 0.2),
        created_at: daysAgo(int(dayLo, dayHi)),
      });
    }
  };
  emit(0, 29, nums.posts30);
  emit(31, 180, nums.older);
});

// give planted (non-coldstart) users a couple of memberships UNRELATED to their
// scenario topic, so "already joined" never collides with the circles we expect
// the recommender to surface.
function joinSome(uid, n) {
  const interests = new Set(byId(uid).topic_interests);
  const options = circles.filter((c) => !c.topic || !interests.has(c.topic));
  for (const c of sampleUnique(options, n)) {
    memberships.push({ user_id: uid, circle_id: c.id, role: "member", joined_at: daysAgo(int(30, 300)) });
    c.member_count += 1;
    if (c.max_members !== null && c.member_count > c.max_members) c.max_members = c.member_count + 2;
  }
}
joinSome(RESERVED.OBVIOUS, 1);
joinSome(RESERVED.DUP, 2);
joinSome(RESERVED.FULL_TRAP, 1);
// coldstart (42) joins nothing

// ---- write -----------------------------------------------------------------
mkdirSync(DATA, { recursive: true });
const write = (name, obj) => writeFileSync(join(DATA, name), JSON.stringify(obj, null, 2) + "\n");
write("topics.json", TOPICS);
write("users.json", users);
write("circles.json", circles);
write("memberships.json", memberships);
write("activity.json", activity);

// ---- summary (sanity) ------------------------------------------------------
const full = circles.find((c) => c.id === 20);
console.log("topics:", TOPICS.length);
console.log("users:", users.length, "| coldstart(42) interests:", byId(42).topic_interests.length, "completeness:", byId(42).profile_completeness);
console.log("circles:", circles.length, "| memberships:", memberships.length, "| activity posts:", activity.length);
console.log("obvious(7) interests:", byId(7).topic_interests.join(","));
console.log("dup circles 10/11/12 topic:", circles.slice(9, 12).map((c) => c.topic).join(","));
console.log("full circle 20:", full.member_count, "/", full.max_members, "posts30:", full.feed_posts_30d);
console.log("inactive circle 21 posts30:", circles[20].feed_posts_30d, "lastAct:", circles[20].last_activity_at);
console.log(
  "membership rows for reserved users:",
  Object.values(RESERVED).map((id) => `${id}:${memberships.filter((m) => m.user_id === id).length}`).join(" "),
);
