"""
SQLite storage for seller profiles.

Tables are shaped the way the Prisma models in the brief would be -- one table
per entity, real foreign keys, no JSON blob standing in for a relation -- so
moving to Postgres later is a driver swap rather than a redesign. The two
places a JSON column is used (`languages`, `features`) hold ordered lists of
plain strings with no identity of their own; giving them tables would buy
nothing.

`kb/` markdown is no longer the source of truth for profiles. It becomes a
generated export, written alongside every save so a human can still read a
profile in a text editor. Editing that export by hand no longer feeds back in:
flat `## Heading` markdown cannot round-trip three pricing packages per gig,
repeatable FAQs, individual reviews or a per-field null from an OCR run.

Everything is one transaction. A re-onboard deletes the seller's rows and
writes the new ones inside a single commit, so an interrupted save can never
leave half a profile behind.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from . import config
from .schema import (
    About,
    BasicInfo,
    FAQ,
    Gig,
    Package,
    PortfolioItem,
    Review,
    ReviewSummary,
    SellerProfile,
    Skills,
    derive_gig_id,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    seller_id           TEXT PRIMARY KEY,
    name                TEXT,
    username            TEXT,
    profile_photo_url   TEXT,
    country             TEXT,
    languages           TEXT NOT NULL DEFAULT '[]',
    member_since        TEXT,
    avg_response_time   TEXT,
    headline            TEXT,
    level               TEXT,
    bio                 TEXT,
    working_style       TEXT,
    skills              TEXT NOT NULL DEFAULT '[]',
    education           TEXT NOT NULL DEFAULT '[]',
    certifications      TEXT NOT NULL DEFAULT '[]',
    tests               TEXT NOT NULL DEFAULT '[]',
    source_type         TEXT NOT NULL DEFAULT 'manual',
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gigs (
    gig_id      TEXT PRIMARY KEY,
    seller_id   TEXT NOT NULL REFERENCES sellers(seller_id) ON DELETE CASCADE,
    title       TEXT,
    category    TEXT,
    description TEXT,
    extras      TEXT NOT NULL DEFAULT '[]',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gigs_seller ON gigs(seller_id);

CREATE TABLE IF NOT EXISTS packages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gig_id        TEXT NOT NULL REFERENCES gigs(gig_id) ON DELETE CASCADE,
    tier          TEXT,
    name          TEXT,
    price         REAL,
    currency      TEXT,
    delivery_days INTEGER,
    revisions     TEXT,
    features      TEXT NOT NULL DEFAULT '[]',
    position      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_packages_gig ON packages(gig_id);

CREATE TABLE IF NOT EXISTS gig_faqs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    gig_id   TEXT NOT NULL REFERENCES gigs(gig_id) ON DELETE CASCADE,
    question TEXT,
    answer   TEXT,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_faqs_gig ON gig_faqs(gig_id);

CREATE TABLE IF NOT EXISTS portfolio_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id   TEXT NOT NULL REFERENCES sellers(seller_id) ON DELETE CASCADE,
    title       TEXT,
    description TEXT,
    image_url   TEXT,
    link        TEXT,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_portfolio_seller ON portfolio_items(seller_id);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id     TEXT NOT NULL REFERENCES sellers(seller_id) ON DELETE CASCADE,
    text          TEXT,
    stars         REAL,
    buyer_country TEXT,
    date          TEXT,
    position      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reviews_seller ON reviews(seller_id);

CREATE TABLE IF NOT EXISTS review_summary (
    seller_id      TEXT PRIMARY KEY REFERENCES sellers(seller_id) ON DELETE CASCADE,
    overall_rating REAL,
    total_reviews  INTEGER,
    stars_5        INTEGER,
    stars_4        INTEGER,
    stars_3        INTEGER,
    stars_2        INTEGER,
    stars_1        INTEGER
);

-- Drafts are deliberately NOT foreign-keyed to sellers: the whole point is to
-- survive a half-finished profile that has never been saved.
CREATE TABLE IF NOT EXISTS drafts (
    draft_id   TEXT PRIMARY KEY,
    step       INTEGER NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

DEFAULT_DRAFT_ID = "__current__"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(items) -> str:
    return json.dumps([str(i) for i in (items or []) if str(i).strip()])


def _loads(raw) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


@contextmanager
def connect():
    """One connection, foreign keys on, everything inside a transaction."""
    config.PROFILE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.PROFILE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after a version of the schema had already been created
# somewhere. `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
# exists, so without this an upgrade fails on the first write with
# "table X has no column named Y" -- and the database holding real profiles is
# exactly the one that is already there.
#
# Append-only. Each entry is (table, column, type). SQLite's ALTER TABLE can
# add a nullable column cheaply; anything more involved needs a real migration.
ADDED_COLUMNS = [
    ("packages", "currency", "TEXT"),
]


def _apply_column_migrations(conn):
    for table, column, coltype in ADDED_COLUMNS:
        try:
            existing = {r["name"] for r in
                        conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue  # table not created yet; the schema script will make it
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        _apply_column_migrations(conn)


# --- Write -----------------------------------------------------------------

def save_seller(profile: SellerProfile) -> str:
    """Insert or replace one seller and everything hanging off them.

    Delete-then-insert rather than a field-by-field merge: a re-onboard is
    meant to be authoritative, and a merge would silently keep a gig the seller
    deliberately removed.
    """
    init_db()
    seller_id = profile.resolved_seller_id()
    b, a, s = profile.basic, profile.about, profile.skills

    with connect() as conn:
        # ON DELETE CASCADE clears gigs, packages, faqs, portfolio, reviews
        # and the summary in one statement.
        conn.execute("DELETE FROM sellers WHERE seller_id = ?", (seller_id,))
        conn.execute(
            """INSERT INTO sellers (
                   seller_id, name, username, profile_photo_url, country,
                   languages, member_since, avg_response_time, headline, level,
                   bio, working_style, skills, education, certifications, tests,
                   source_type, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                seller_id, b.name, b.username, b.profile_photo_url, b.country,
                _dumps(b.languages), b.member_since, b.avg_response_time,
                b.headline, b.level, a.bio, a.working_style,
                _dumps(s.skills), _dumps(s.education),
                _dumps(s.certifications), _dumps(s.tests),
                profile.source_type, _now(),
            ),
        )

        # gig_id is a global primary key, so it has to be unique across every
        # seller, not just within one. An id that does not already belong to
        # this seller is replaced rather than trusted: it can arrive from an
        # OCR extraction, from a draft written under a different username, or
        # from a second seller who happens to sell the same thing.
        used = set()
        for gi, gig in enumerate(profile.gigs):
            gig_id = gig.gig_id or ""
            if not gig_id.startswith(f"{seller_id}__"):
                gig_id = derive_gig_id(seller_id, gig.title, gi)
            base, suffix = gig_id, 2
            while gig_id in used:  # two gigs with the same title
                gig_id = f"{base}_{suffix}"
                suffix += 1
            used.add(gig_id)
            # Write it back so the caller's in-memory profile matches the rows,
            # and the documents built from it carry the same gigId.
            gig.gig_id = gig_id

            conn.execute(
                """INSERT INTO gigs (gig_id, seller_id, title, category,
                                     description, extras, position)
                   VALUES (?,?,?,?,?,?,?)""",
                (gig_id, seller_id, gig.title, gig.category, gig.description,
                 _dumps(gig.extras), gi),
            )
            for pi, pkg in enumerate(gig.packages):
                conn.execute(
                    """INSERT INTO packages (gig_id, tier, name, price,
                                             currency, delivery_days, revisions,
                                             features, position)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (gig_id, pkg.tier, pkg.name, pkg.price, pkg.currency,
                     pkg.delivery_days, pkg.revisions, _dumps(pkg.features), pi),
                )
            for fi, faq in enumerate(gig.faqs):
                conn.execute(
                    "INSERT INTO gig_faqs (gig_id, question, answer, position)"
                    " VALUES (?,?,?,?)",
                    (gig_id, faq.question, faq.answer, fi),
                )

        for pi, item in enumerate(profile.portfolio):
            conn.execute(
                """INSERT INTO portfolio_items (seller_id, title, description,
                                                image_url, link, position)
                   VALUES (?,?,?,?,?,?)""",
                (seller_id, item.title, item.description, item.image_url,
                 item.link, pi),
            )

        for ri, review in enumerate(profile.reviews):
            conn.execute(
                """INSERT INTO reviews (seller_id, text, stars, buyer_country,
                                        date, position)
                   VALUES (?,?,?,?,?,?)""",
                (seller_id, review.text, review.stars, review.buyer_country,
                 review.date, ri),
            )

        rs = profile.review_summary
        conn.execute(
            """INSERT INTO review_summary (seller_id, overall_rating,
                   total_reviews, stars_5, stars_4, stars_3, stars_2, stars_1)
               VALUES (?,?,?,?,?,?,?,?)""",
            (seller_id, rs.overall_rating, rs.total_reviews, rs.stars_5,
             rs.stars_4, rs.stars_3, rs.stars_2, rs.stars_1),
        )

    return seller_id


def delete_seller(seller_id: str) -> bool:
    init_db()
    with connect() as conn:
        cur = conn.execute("DELETE FROM sellers WHERE seller_id = ?", (seller_id,))
        return cur.rowcount > 0


# --- Read ------------------------------------------------------------------

def load_seller(seller_id: str) -> Optional[SellerProfile]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)
        ).fetchone()
        if row is None:
            return None

        gigs = []
        for g in conn.execute(
            "SELECT * FROM gigs WHERE seller_id = ? ORDER BY position, gig_id",
            (seller_id,),
        ).fetchall():
            packages = [
                Package(
                    tier=p["tier"], name=p["name"], price=p["price"],
                    currency=p["currency"], delivery_days=p["delivery_days"],
                    revisions=p["revisions"], features=_loads(p["features"]),
                )
                for p in conn.execute(
                    "SELECT * FROM packages WHERE gig_id = ? ORDER BY position, id",
                    (g["gig_id"],),
                ).fetchall()
            ]
            faqs = [
                FAQ(question=f["question"], answer=f["answer"])
                for f in conn.execute(
                    "SELECT * FROM gig_faqs WHERE gig_id = ? ORDER BY position, id",
                    (g["gig_id"],),
                ).fetchall()
            ]
            gigs.append(Gig(
                gig_id=g["gig_id"], title=g["title"], category=g["category"],
                description=g["description"], extras=_loads(g["extras"]),
                packages=packages, faqs=faqs,
            ))

        portfolio = [
            PortfolioItem(title=p["title"], description=p["description"],
                          image_url=p["image_url"], link=p["link"])
            for p in conn.execute(
                "SELECT * FROM portfolio_items WHERE seller_id = ?"
                " ORDER BY position, id", (seller_id,),
            ).fetchall()
        ]

        reviews = [
            Review(text=r["text"], stars=r["stars"],
                   buyer_country=r["buyer_country"], date=r["date"])
            for r in conn.execute(
                "SELECT * FROM reviews WHERE seller_id = ? ORDER BY position, id",
                (seller_id,),
            ).fetchall()
        ]

        srow = conn.execute(
            "SELECT * FROM review_summary WHERE seller_id = ?", (seller_id,)
        ).fetchone()
        summary = ReviewSummary(
            overall_rating=srow["overall_rating"],
            total_reviews=srow["total_reviews"],
            stars_5=srow["stars_5"], stars_4=srow["stars_4"],
            stars_3=srow["stars_3"], stars_2=srow["stars_2"],
            stars_1=srow["stars_1"],
        ) if srow else ReviewSummary()

    return SellerProfile(
        seller_id=row["seller_id"],
        basic=BasicInfo(
            name=row["name"], username=row["username"],
            profile_photo_url=row["profile_photo_url"], country=row["country"],
            languages=_loads(row["languages"]), member_since=row["member_since"],
            avg_response_time=row["avg_response_time"], headline=row["headline"],
            level=row["level"],
        ),
        about=About(bio=row["bio"], working_style=row["working_style"]),
        skills=Skills(
            skills=_loads(row["skills"]), education=_loads(row["education"]),
            certifications=_loads(row["certifications"]), tests=_loads(row["tests"]),
        ),
        gigs=gigs, portfolio=portfolio, reviews=reviews, review_summary=summary,
        source_type=row["source_type"] or "manual",
    )


def list_sellers() -> List[dict]:
    """Every seller, most recently updated first. Summary rows only."""
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.seller_id, s.name, s.username, s.source_type,
                      s.updated_at, COUNT(g.gig_id) AS gig_count
               FROM sellers s
               LEFT JOIN gigs g ON g.seller_id = s.seller_id
               GROUP BY s.seller_id
               ORDER BY s.updated_at DESC""",
        ).fetchall()
    return [dict(r) for r in rows]


def load_all_sellers() -> List[SellerProfile]:
    return [p for p in (load_seller(r["seller_id"]) for r in list_sellers()) if p]


# --- Drafts ----------------------------------------------------------------

def save_draft(profile: SellerProfile, step: int = 0,
               draft_id: str = DEFAULT_DRAFT_ID) -> None:
    """Persist a half-finished profile between steps.

    Stored as the model's JSON rather than in the real tables: a draft is
    allowed to be invalid, and putting it in `sellers` would make it visible to
    retrieval before the seller ever pressed save.
    """
    init_db()
    with connect() as conn:
        conn.execute(
            """INSERT INTO drafts (draft_id, step, payload, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(draft_id) DO UPDATE SET
                   step = excluded.step,
                   payload = excluded.payload,
                   updated_at = excluded.updated_at""",
            (draft_id, int(step), profile.model_dump_json(), _now()),
        )


def load_draft(draft_id: str = DEFAULT_DRAFT_ID):
    """(profile, step) or (None, 0). A draft written by an older schema is
    discarded rather than crashing the wizard on load."""
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT step, payload FROM drafts WHERE draft_id = ?", (draft_id,)
        ).fetchone()
    if row is None:
        return None, 0
    try:
        return SellerProfile.model_validate_json(row["payload"]), row["step"]
    except Exception:
        return None, 0


def clear_draft(draft_id: str = DEFAULT_DRAFT_ID) -> None:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM drafts WHERE draft_id = ?", (draft_id,))


def has_draft(draft_id: str = DEFAULT_DRAFT_ID) -> bool:
    return load_draft(draft_id)[0] is not None
