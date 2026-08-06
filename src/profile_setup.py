"""
Profile onboarding -- the logic behind the six-step wizard.

The seller's profile lives in SQLite (`store.py`), described by one shared
schema (`schema.py`), and is turned into retrievable text by `documents.py`.
This module is the layer the UI talks to: it declares which fields appear in
which step, converts between the flat strings a form produces and the typed
models everything else uses, and owns the save-and-reindex sequence.

Markdown under `kb/profile_gigs/` is still written on every save, but only as a
human-readable export. Earlier versions parsed it back as the source of truth;
that stopped when the schema grew three pricing packages per gig, repeatable
FAQs, portfolio items and individual reviews, none of which survive a round
trip through flat `## Heading` markdown.
"""
from pathlib import Path
from typing import List, Optional

from . import config, documents, store
from .schema import (
    About,
    BasicInfo,
    FAQ,
    Gig,
    LEVELS,
    MAX_BIO_CHARS,
    MAX_PACKAGES,
    MAX_SKILLS,
    PACKAGE_TIERS,
    Package,
    PortfolioItem,
    Review,
    ReviewSummary,
    SellerProfile,
    STEPS,
    STEP_KEYS,
    Skills,
    derive_seller_id,
    profile_status as _schema_status,
    slugify,
    validate_profile,
    validate_step,
)

EXPORT_SUFFIX = "_profile.md"

# Files the pre-SQLite wizard wrote. They are still valid KB content and are
# still indexed; the migration script imports them into the store.
LEGACY_PROFILE_FILENAME = "seller_profile.md"


class Field:
    """One question in the wizard.

    kind: "text" (one line) | "textarea" (paragraph) | "list" (one item per
    line) | "select" (one of `options`) | "number" | "int".

    `path` is where the value lives on a SellerProfile, dotted --
    "basic.username". That is what keeps the form, the schema and the database
    from drifting: a field is defined once and read from the model by path.
    """

    def __init__(self, key, label, path, kind="text", required=False,
                 help="", placeholder="", options=None, max_chars=None,
                 max_items=None):
        self.key = key
        self.label = label
        self.path = path
        self.kind = kind
        self.required = required
        self.help = help
        self.placeholder = placeholder
        self.options = options or []
        self.max_chars = max_chars
        self.max_items = max_items


# --- Step 1: Basic information ---------------------------------------------

BASIC_FIELDS = [
    Field("name", "Your name (as it appears to buyers)", "basic.name",
          required=True,
          help="The name buyers see on your profile, not your login username.",
          placeholder="Syed Haseeb"),
    Field("username", "Fiverr username", "basic.username", required=True,
          help="Your @handle. Used as the unique id for this seller.",
          placeholder="syedhaseeb"),
    Field("profile_photo_url", "Profile photo URL", "basic.profile_photo_url",
          help="A link to your profile picture. Optional.",
          placeholder="https://..."),
    Field("country", "Country", "basic.country", placeholder="Pakistan"),
    Field("languages", "Languages", "basic.languages", kind="list", required=True,
          help="One per line. Add the fluency level, e.g. 'Urdu (native)'.",
          placeholder="English (fluent)\nUrdu (native)"),
    Field("member_since", "Member since", "basic.member_since",
          help="As Fiverr shows it on your profile.", placeholder="Mar 2023"),
    Field("avg_response_time", "Average response time", "basic.avg_response_time",
          help="As Fiverr shows it, e.g. '1 hour'.", placeholder="1 hour"),
    Field("headline", "Professional headline", "basic.headline",
          help="Your occupation in one line, shown under your name.",
          placeholder="AI Automation Engineer | n8n, AI Agents"),
    Field("level", "Fiverr level", "basic.level", kind="select", options=LEVELS,
          help="Used when the brain reasons about what you can promise a buyer."),
]

# --- Step 2: About / bio ----------------------------------------------------

ABOUT_FIELDS = [
    Field("bio", "Professional description (bio)", "about.bio",
          kind="textarea", required=True, max_chars=MAX_BIO_CHARS,
          help=f"Fiverr allows {MAX_BIO_CHARS} characters. Write it in first person.",
          placeholder="I build AI-powered automations that remove manual work..."),
    Field("working_style", "Working style & tone", "about.working_style",
          kind="textarea",
          help="How you work with buyers. The brain copies this tone in /buyer-reply.",
          placeholder="Fast delivery, clear communication, documented deliverables."),
]

# --- Step 3: Skills ---------------------------------------------------------

SKILLS_FIELDS = [
    Field("skills", "Skills", "skills.skills", kind="list", required=True,
          max_items=MAX_SKILLS,
          help=f"One per line, up to {MAX_SKILLS}. These are what buyers search for.",
          placeholder="n8n workflow automation\nAI agent development"),
    Field("education", "Education", "skills.education", kind="list",
          help="One per line: qualification, institution, year.",
          placeholder="BS Computer Science, NED University, 2023"),
    Field("certifications", "Certifications", "skills.certifications", kind="list",
          help="They carry weight in professional categories.",
          placeholder="OpenAI API Developer\nMake.com Certified Partner"),
    Field("tests", "Fiverr skill tests", "skills.tests", kind="list",
          help="Tests you have taken, with the score if you have it.",
          placeholder="English (US) — Basic, 9/10"),
]

# --- Step 4: Gigs -----------------------------------------------------------

GIG_FIELDS = [
    Field("title", "Gig title", "title", required=True,
          help="Start it the way Fiverr does: 'I will ...'",
          placeholder="I will build an n8n automation workflow for your business"),
    Field("category", "Category", "category",
          placeholder="Programming & Tech > AI & Automation"),
    Field("description", "What this gig delivers", "description",
          kind="textarea", required=True,
          help="The gig description as a buyer reads it.",
          placeholder="I design and build production-ready n8n workflows..."),
    Field("extras", "Gig extras & add-ons", "extras", kind="list",
          help="One per line.",
          placeholder="Extra fast 24h delivery +$40\nAdditional revision +$15"),
]

PACKAGE_FIELDS = [
    Field("name", "Package name", "name", placeholder="Starter workflow"),
    Field("price", "Price", "price", kind="number", placeholder="50"),
    Field("currency", "Currency", "currency", placeholder="USD",
          help="As Fiverr shows it to you — USD, PKR, EUR."),
    Field("delivery_days", "Delivery (days)", "delivery_days", kind="int",
          placeholder="3"),
    Field("revisions", "Revisions", "revisions", placeholder="1"),
    Field("features", "Included features", "features", kind="list",
          help="One per line — what the buyer gets at this tier.",
          placeholder="1 workflow\nUp to 3 nodes\nHandover call"),
]

# --- Step 5: Portfolio ------------------------------------------------------

PORTFOLIO_FIELDS = [
    Field("title", "Title", "title", required=True,
          placeholder="Invoice processing automation"),
    Field("description", "Description", "description", kind="textarea",
          placeholder="Cut a 4-hour weekly task to 10 minutes for a logistics client."),
    Field("image_url", "Image URL", "image_url", placeholder="https://..."),
    Field("link", "Link", "link", placeholder="https://..."),
]

# --- Step 6: Reviews --------------------------------------------------------

REVIEW_SUMMARY_FIELDS = [
    Field("overall_rating", "Overall rating (0-5)", "overall_rating",
          kind="number", placeholder="4.9"),
    Field("total_reviews", "Total review count", "total_reviews", kind="int",
          placeholder="132"),
    Field("stars_5", "5-star reviews", "stars_5", kind="int"),
    Field("stars_4", "4-star reviews", "stars_4", kind="int"),
    Field("stars_3", "3-star reviews", "stars_3", kind="int"),
    Field("stars_2", "2-star reviews", "stars_2", kind="int"),
    Field("stars_1", "1-star reviews", "stars_1", kind="int"),
]

REVIEW_FIELDS = [
    Field("text", "Review text", "text", kind="textarea",
          placeholder="Delivered ahead of schedule and the workflow just works."),
    Field("stars", "Stars (0-5)", "stars", kind="number", placeholder="5"),
    Field("buyer_country", "Buyer country", "buyer_country",
          placeholder="United States"),
    Field("date", "Date", "date", placeholder="2 weeks ago"),
]

FIELDS_BY_STEP = {
    "basic": BASIC_FIELDS,
    "about": ABOUT_FIELDS,
    "skills": SKILLS_FIELDS,
    "gigs": GIG_FIELDS,
    "portfolio": PORTFOLIO_FIELDS,
    "reviews": REVIEW_FIELDS,
}


# --- Coercion between form strings and typed models -------------------------

def split_lines(value) -> List[str]:
    """Normalise a textarea of one-per-line items into a clean list."""
    raw = value if isinstance(value, (list, tuple)) else str(value or "").splitlines()
    out = []
    for line in raw:
        item = str(line).strip().lstrip("-*•").strip()
        if item and item not in out:
            out.append(item)
    return out


def to_number(value) -> Optional[float]:
    """'$1,250' -> 1250.0, '' -> None. A form gives strings; the schema wants
    numbers, and a stray currency symbol should not become a validation error
    the seller has to decode."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", "").replace("$", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def to_int(value) -> Optional[int]:
    n = to_number(value)
    return None if n is None else int(n)


def coerce(field: Field, value):
    if field.kind == "list":
        return split_lines(value)
    if field.kind == "number":
        return to_number(value)
    if field.kind == "int":
        return to_int(value)
    return str(value or "").strip()


def get_by_path(profile: SellerProfile, path: str):
    obj = profile
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


# --- Building a profile from form values ------------------------------------

def build_profile(values: dict, gigs=None, portfolio=None, reviews=None,
                  seller_id=None, source_type="manual") -> SellerProfile:
    """Assemble a SellerProfile from the flat dict the wizard holds.

    `values` is keyed by Field.key for the four scalar steps; the repeatable
    sections come in as already-built lists.
    """
    def pick(fields):
        return {f.key: coerce(f, values.get(f.key)) for f in fields}

    basic = pick(BASIC_FIELDS)
    about = pick(ABOUT_FIELDS)
    skills = pick(SKILLS_FIELDS)
    summary = {f.key: coerce(f, values.get(f.key)) for f in REVIEW_SUMMARY_FIELDS}

    return SellerProfile(
        seller_id=seller_id or derive_seller_id(basic.get("username"),
                                                basic.get("name")),
        basic=BasicInfo(**basic),
        about=About(**about),
        skills=Skills(**skills),
        gigs=list(gigs or []),
        portfolio=list(portfolio or []),
        reviews=list(reviews or []),
        review_summary=ReviewSummary(**summary),
        source_type=source_type if source_type in ("manual", "ocr") else "manual",
    )


def flatten_profile(profile: SellerProfile) -> dict:
    """The inverse of build_profile for the scalar steps -- what the widgets
    need as their initial values."""
    values = {}
    for fields in (BASIC_FIELDS, ABOUT_FIELDS, SKILLS_FIELDS):
        for f in fields:
            values[f.key] = get_by_path(profile, f.path)
    for f in REVIEW_SUMMARY_FIELDS:
        values[f.key] = getattr(profile.review_summary, f.key)
    return values


def build_package(tier: str, values: dict) -> Package:
    fields = {f.key: f for f in PACKAGE_FIELDS}
    return Package(
        tier=tier,
        **{key: coerce(field, values.get(key)) for key, field in fields.items()},
    )


def package_is_empty(pkg: Package) -> bool:
    """A tier the seller left blank should not be saved as a nameless $0
    package -- it would show up in retrieval as a real offer. A currency on its
    own does not count as content: the form can carry a default.
    """
    return not any([
        (pkg.name or "").strip(), pkg.price is not None,
        pkg.delivery_days is not None, (pkg.revisions or "").strip(),
        pkg.features,
    ])


def build_gig(values: dict, packages=None, faqs=None, gig_id=None) -> Gig:
    kept = [p for p in (packages or []) if not package_is_empty(p)]
    return Gig(
        gig_id=gig_id,
        title=coerce(GIG_FIELDS[0], values.get("title")),
        category=coerce(GIG_FIELDS[1], values.get("category")),
        description=coerce(GIG_FIELDS[2], values.get("description")),
        extras=coerce(GIG_FIELDS[3], values.get("extras")),
        packages=kept,
        faqs=[f for f in (faqs or [])
              if (f.question or "").strip() or (f.answer or "").strip()],
    )


def build_portfolio_item(values: dict) -> PortfolioItem:
    return PortfolioItem(**{f.key: coerce(f, values.get(f.key))
                            for f in PORTFOLIO_FIELDS})


def build_review(values: dict) -> Review:
    return Review(**{f.key: coerce(f, values.get(f.key)) for f in REVIEW_FIELDS})


def empty_gig() -> Gig:
    return Gig(packages=[Package(tier=t) for t in PACKAGE_TIERS])


def padded_packages(gig: Gig) -> List[Package]:
    """The three tiers in order, blanks included, so the form always draws
    Basic / Standard / Premium even on a gig that only has one."""
    by_tier = {p.tier: p for p in gig.packages if p.tier}
    untiered = [p for p in gig.packages if not p.tier]
    out = []
    for tier in PACKAGE_TIERS:
        if tier in by_tier:
            out.append(by_tier[tier])
        elif untiered:
            out.append(untiered.pop(0).model_copy(update={"tier": tier}))
        else:
            out.append(Package(tier=tier))
    return out


# --- Persistence ------------------------------------------------------------

def _kb_dir() -> Path:
    return Path(config.KB_FOLDERS["profile_gigs"])


def _safe_export_target(seller_id: str) -> Path:
    """Resolve the export filename inside kb/profile_gigs, refusing anything
    that would escape the folder (same rule as new_gig.save_and_reindex).

    A seller_id is derived from a username the seller types, so it is untrusted
    input on a filesystem path even though slugify should already have made it
    harmless.
    """
    folder = _kb_dir().resolve()
    safe = Path(slugify(seller_id, fallback="seller") + EXPORT_SUFFIX).name
    target = folder / safe
    if target.resolve().parent != folder:
        raise ValueError("Refusing to write outside the knowledge base folder.")
    return target


def write_export(profile: SellerProfile) -> Optional[Path]:
    """Write the human-readable markdown export. Best effort: the profile is
    already safely in SQLite by the time this runs, so a read-only kb/ folder
    must not turn a successful save into a failure."""
    try:
        target = _safe_export_target(profile.resolved_seller_id())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(documents.render_markdown(profile), encoding="utf-8")
        return target
    except (OSError, ValueError):
        return None


def save_profile(profile: SellerProfile, validate: bool = True) -> str:
    """Persist a seller and refresh their export. Returns the seller id."""
    if validate:
        problems = validate_profile(profile)
        if problems:
            raise ValueError(problems[0])
    seller_id = store.save_seller(profile)
    write_export(profile)
    return seller_id


def load_profile(seller_id: str = None) -> Optional[SellerProfile]:
    """A specific seller, or the most recently updated one when not named."""
    if seller_id:
        return store.load_seller(seller_id)
    sellers = store.list_sellers()
    return store.load_seller(sellers[0]["seller_id"]) if sellers else None


def list_sellers() -> List[dict]:
    return store.list_sellers()


def delete_profile(seller_id: str) -> bool:
    """Remove a seller from the store, their export, and their vectors."""
    removed = store.delete_seller(seller_id)
    try:
        _safe_export_target(seller_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    return removed


def profile_status(profile: SellerProfile = None) -> dict:
    if profile is None:
        profile = load_profile()
    return _schema_status(profile)


def apply_to_index(profile: SellerProfile, brain=None, warn=None) -> int:
    """Push one seller's documents into the vector store.

    Nothing the wizard writes is visible to retrieval until this runs. Only
    this seller's vectors are touched -- other sellers, policies and SOPs are
    left alone.
    """
    from . import ingest

    count = ingest.upsert_seller(profile, warn=warn)
    if brain is not None:
        brain.refresh_collection()
    return count


def remove_from_index(seller_id: str, brain=None) -> None:
    from . import ingest

    ingest.delete_seller_vectors(seller_id)
    if brain is not None:
        brain.refresh_collection()


# --- Drafts -----------------------------------------------------------------

def save_draft(profile: SellerProfile, step: int = 0) -> None:
    store.save_draft(profile, step=step)


def load_draft():
    return store.load_draft()


def clear_draft() -> None:
    store.clear_draft()


# --- Optional LLM assist ----------------------------------------------------

BIO_INSTRUCTIONS = """You are writing the "professional description" (bio) for a
Fiverr seller profile, in the seller's own first-person voice.
Rules:
- Hard limit of {limit} characters. Shorter is fine.
- Lead with what the buyer gets, not with a life story.
- Plain, confident language. No hype words ("world-class", "ninja", "guru").
- No emojis, no headings, no bullet points -- one flowing block of prose.
Return the bio text only, with nothing before or after it."""


def suggest_bio(brain, profile: SellerProfile) -> str:
    """Draft a bio from the answers already given. Optional -- the wizard
    works fine without ever calling the LLM."""
    from .rag import fence

    facts = []
    for fields in (BASIC_FIELDS, SKILLS_FIELDS):
        for field in fields:
            value = get_by_path(profile, field.path)
            rendered = ", ".join(str(v) for v in value) if isinstance(value, list) \
                else str(value or "").strip()
            if rendered:
                facts.append(f"{field.label}: {rendered}")
    for gig in profile.gigs:
        if gig.title:
            facts.append(f"Gig: {gig.title}")

    if not facts:
        raise ValueError("Fill in your name, username and skills first.")

    prompt = (
        BIO_INSTRUCTIONS.format(limit=MAX_BIO_CHARS) + "\n\n"
        + fence("\n".join(facts), "seller_answers")
        + "\n\nWrite the bio now."
    )
    bio = brain._call_llm(prompt).strip().strip('"')
    return bio[:MAX_BIO_CHARS]


# Re-exported so callers keep importing one module.
__all__ = [
    "Field", "BASIC_FIELDS", "ABOUT_FIELDS", "SKILLS_FIELDS", "GIG_FIELDS",
    "PACKAGE_FIELDS", "PORTFOLIO_FIELDS", "REVIEW_SUMMARY_FIELDS",
    "REVIEW_FIELDS", "FIELDS_BY_STEP", "STEPS", "STEP_KEYS", "LEVELS",
    "MAX_BIO_CHARS", "MAX_SKILLS", "MAX_PACKAGES", "PACKAGE_TIERS",
    "build_profile", "flatten_profile", "build_gig", "build_package",
    "build_portfolio_item", "build_review", "empty_gig", "padded_packages",
    "package_is_empty", "save_profile", "load_profile", "list_sellers",
    "delete_profile", "profile_status", "apply_to_index", "remove_from_index",
    "save_draft", "load_draft", "clear_draft", "suggest_bio", "slugify",
    "split_lines", "to_number", "to_int", "validate_step", "validate_profile",
    "write_export", "SellerProfile", "Gig", "Package", "FAQ", "PortfolioItem",
    "Review", "ReviewSummary",
]
