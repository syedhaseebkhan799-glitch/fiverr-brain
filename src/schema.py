"""
The single shared schema. One definition drives three consumers:

  * the onboarding form   -- field lists and validation come from these models
  * the OCR extractor     -- the vision model is handed this schema as JSON, so
                             the extractor literally cannot drift from the form
  * the SQLite layer      -- store.py reads and writes these models, nothing else

Every field is optional at the model level. That is deliberate: a screenshot
shows a fraction of a profile and a half-finished draft shows even less, so the
models have to be able to represent "not known yet" without lying. What makes a
profile *complete enough to save* is a separate question, answered by
`validate_profile()` -- the required-field rules live there, applied per step,
not baked into types that the OCR path also has to satisfy.
"""
import re
import unicodedata
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Fiverr's own limits, so a profile drafted here can be pasted straight into
# the real thing.
MAX_BIO_CHARS = 600
MAX_SKILLS = 30
MAX_PACKAGES = 3

PACKAGE_TIERS = ("basic", "standard", "premium")

LEVELS = [
    "New Seller",
    "Level 1",
    "Level 2",
    "Top Rated Seller",
    "Fiverr Pro",
]

SOURCE_TYPES = ("manual", "ocr")


class _Model(BaseModel):
    # extra="forbid" is what makes pydantic emit `additionalProperties: false`,
    # which Claude's structured-output mode requires.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Package(_Model):
    """One of the three pricing tiers on a gig."""

    tier: Optional[str] = Field(
        None, description="One of: basic, standard, premium."
    )
    name: Optional[str] = Field(None, description="The package's display name.")
    price: Optional[float] = Field(None, description="The price, digits only.")
    # Fiverr shows prices in the viewer's local currency, so a screenshot may
    # say PKR or EUR. Converting to USD would be inventing a number nobody can
    # check against the image; recording the currency keeps it honest.
    currency: Optional[str] = Field(
        None, description="Currency code or symbol as shown, e.g. 'USD', 'PKR'."
    )
    delivery_days: Optional[int] = Field(None, description="Delivery time in days.")
    revisions: Optional[str] = Field(
        None, description="Number of revisions, or 'unlimited'."
    )
    features: List[str] = Field(
        default_factory=list, description="What this package includes, one per item."
    )

    @field_validator("tier")
    @classmethod
    def _normalise_tier(cls, v):
        if v is None:
            return None
        v = v.strip().lower()
        return v if v in PACKAGE_TIERS else None


class FAQ(_Model):
    question: Optional[str] = None
    answer: Optional[str] = None


class Gig(_Model):
    gig_id: Optional[str] = Field(
        None, description="Leave null; the system assigns it."
    )
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = Field(
        None, description="The full gig description as a buyer reads it."
    )
    packages: List[Package] = Field(default_factory=list)
    extras: List[str] = Field(
        default_factory=list, description="Gig extras / add-ons, one per item."
    )
    faqs: List[FAQ] = Field(default_factory=list)


class PortfolioItem(_Model):
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    link: Optional[str] = None


class Review(_Model):
    text: Optional[str] = None
    stars: Optional[float] = Field(None, description="1 to 5.")
    buyer_country: Optional[str] = None
    date: Optional[str] = Field(None, description="As shown, e.g. '2 weeks ago'.")


class ReviewSummary(_Model):
    overall_rating: Optional[float] = Field(None, description="1 to 5.")
    total_reviews: Optional[int] = None
    stars_5: Optional[int] = Field(None, description="Count of 5-star reviews.")
    stars_4: Optional[int] = None
    stars_3: Optional[int] = None
    stars_2: Optional[int] = None
    stars_1: Optional[int] = None

    def breakdown(self) -> dict:
        return {n: getattr(self, f"stars_{n}") for n in range(5, 0, -1)}


class BasicInfo(_Model):
    name: Optional[str] = Field(None, description="Display name shown to buyers.")
    username: Optional[str] = Field(None, description="Fiverr @username.")
    profile_photo_url: Optional[str] = None
    country: Optional[str] = None
    languages: List[str] = Field(
        default_factory=list, description="e.g. 'English (fluent)'."
    )
    member_since: Optional[str] = Field(None, description="e.g. 'Mar 2023'.")
    avg_response_time: Optional[str] = Field(None, description="e.g. '1 hour'.")
    headline: Optional[str] = Field(
        None, description="One-line occupation shown under the name."
    )
    level: Optional[str] = Field(
        None, description="Fiverr level, e.g. 'Level 2', 'Top Rated Seller'."
    )


class About(_Model):
    bio: Optional[str] = Field(
        None, description=f"Full seller description, max {MAX_BIO_CHARS} characters."
    )
    working_style: Optional[str] = Field(
        None, description="How the seller works with buyers. Tone reference."
    )


class Skills(_Model):
    skills: List[str] = Field(
        default_factory=list, description=f"Skill tags, up to {MAX_SKILLS}."
    )
    education: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    tests: List[str] = Field(
        default_factory=list, description="Fiverr skill tests taken, with scores."
    )


class SellerProfile(_Model):
    """One Fiverr seller, all six sections."""

    seller_id: Optional[str] = Field(
        None, description="Leave null; the system derives it from the username."
    )
    basic: BasicInfo = Field(default_factory=BasicInfo)
    about: About = Field(default_factory=About)
    skills: Skills = Field(default_factory=Skills)
    gigs: List[Gig] = Field(default_factory=list)
    portfolio: List[PortfolioItem] = Field(default_factory=list)
    reviews: List[Review] = Field(default_factory=list)
    review_summary: ReviewSummary = Field(default_factory=ReviewSummary)
    source_type: str = Field(
        "manual", description="'manual' or 'ocr'. Leave as manual."
    )

    def resolved_seller_id(self) -> str:
        """Stable id for namespacing this seller's vectors and rows."""
        return self.seller_id or derive_seller_id(
            self.basic.username, self.basic.name
        )


class ScreenshotReading(_Model):
    """The vision model's whole answer to one screenshot.

    The gate comes first: before extracting anything, the model has to say
    whether the image is from Fiverr at all. A random photo, a WhatsApp chat or
    an Upwork profile must be refused with an explanation, not silently turned
    into an empty profile -- an empty profile looks like a bad extraction,
    while a refusal tells the user what actually happened.
    """

    is_fiverr_screenshot: bool = Field(
        False,
        description=(
            "True ONLY if the image clearly shows Fiverr: a fiverr.com page or "
            "the Fiverr app -- a seller profile, gig page, order page, inbox, "
            "dashboard, earnings, analytics or reviews. False for anything "
            "else, including other freelance platforms."
        ),
    )
    image_shows: Optional[str] = Field(
        None,
        description=(
            "One short sentence describing what the image actually shows, "
            "e.g. 'A Fiverr gig page for logo design' or 'A photo of a cat'."
        ),
    )
    profile: SellerProfile = Field(default_factory=SellerProfile)


# --- Identity --------------------------------------------------------------

def slugify(text: str, fallback: str = "") -> str:
    """'I will build n8n workflows!' -> 'build_n8n_workflows'."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"^\s*i\s+will\s+", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:60] or fallback


def derive_seller_id(username=None, name=None) -> str:
    """Prefer the username -- it is the thing Fiverr guarantees is unique."""
    return slugify(username) or slugify(name) or "seller"


def derive_gig_id(seller_id: str, title: str, index: int = 0) -> str:
    slug = slugify(title, fallback=f"gig_{index + 1}")
    return f"{seller_id}__{slug}"


def format_number(value) -> str:
    """A price or rating as text, without losing cents.

    `%g` would render 11667.42 as "11667.4" -- six significant digits is fine
    for a rating and wrong for a price. This keeps two decimal places when
    there are any and drops them when there are not, so 50.0 stays "50".
    """
    if value is None:
        return ""
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


# --- Validation ------------------------------------------------------------
#
# The six steps of the wizard. `required` here is what blocks a step from
# advancing and what blocks a save -- it is not enforced by the models, because
# the OCR and draft paths must be able to hold a partial profile.

STEPS = [
    {
        "key": "basic",
        "number": 1,
        "title": "Basic information",
        "help": "Who you are. Everything the brain says about you starts here.",
    },
    {
        "key": "about",
        "number": 2,
        "title": "About / bio",
        "help": "Your seller description, in your own voice.",
    },
    {
        "key": "skills",
        "number": 3,
        "title": "Skills",
        "help": "Skills, education, certifications and Fiverr skill tests.",
    },
    {
        "key": "gigs",
        "number": 4,
        "title": "Gigs",
        "help": "Each gig with its three pricing packages, extras and FAQs.",
    },
    {
        "key": "portfolio",
        "number": 5,
        "title": "Projects / portfolio",
        "help": "Work samples buyers can look at.",
    },
    {
        "key": "reviews",
        "number": 6,
        "title": "Reviews and ratings",
        "help": "Your rating, review count and the reviews themselves.",
    },
]

STEP_KEYS = [s["key"] for s in STEPS]


def _filled(value) -> bool:
    if isinstance(value, (list, tuple)):
        return any(str(v).strip() for v in value if v is not None)
    return bool(str(value or "").strip())


def validate_step(profile: SellerProfile, step_key: str) -> List[str]:
    """Problems that must be fixed before this step is considered done.

    Empty list means the step passes. Steps 5 and 6 have no required fields --
    a seller with no portfolio and no reviews yet is a real seller, not an
    invalid one.
    """
    p = profile
    problems: List[str] = []

    if step_key == "basic":
        if not _filled(p.basic.name):
            problems.append("Name is required.")
        if not _filled(p.basic.username):
            problems.append("Fiverr username is required.")
        if not _filled(p.basic.languages):
            problems.append("At least one language is required.")

    elif step_key == "about":
        if not _filled(p.about.bio):
            problems.append("The bio is required.")
        elif len(p.about.bio) > MAX_BIO_CHARS:
            problems.append(
                f"The bio is {len(p.about.bio)} characters — "
                f"Fiverr allows {MAX_BIO_CHARS}."
            )

    elif step_key == "skills":
        if not _filled(p.skills.skills):
            problems.append("At least one skill is required.")
        elif len(p.skills.skills) > MAX_SKILLS:
            problems.append(
                f"{len(p.skills.skills)} skills — Fiverr allows {MAX_SKILLS}."
            )

    elif step_key == "gigs":
        if not p.gigs:
            problems.append("Add at least one gig.")
        for i, gig in enumerate(p.gigs, start=1):
            label = gig.title.strip() if _filled(gig.title) else f"Gig {i}"
            if not _filled(gig.title):
                problems.append(f"Gig {i}: a title is required.")
            if not _filled(gig.description):
                problems.append(f"{label}: a description is required.")
            if len(gig.packages) > MAX_PACKAGES:
                problems.append(
                    f"{label}: {len(gig.packages)} packages — "
                    f"Fiverr allows {MAX_PACKAGES}."
                )
            seen = set()
            for pkg in gig.packages:
                if pkg.tier and pkg.tier in seen:
                    problems.append(f"{label}: two '{pkg.tier}' packages.")
                if pkg.tier:
                    seen.add(pkg.tier)
            for j, faq in enumerate(gig.faqs, start=1):
                if _filled(faq.question) != _filled(faq.answer):
                    problems.append(
                        f"{label}: FAQ {j} needs both a question and an answer."
                    )

    elif step_key == "portfolio":
        for i, item in enumerate(p.portfolio, start=1):
            if not _filled(item.title):
                problems.append(f"Portfolio item {i}: a title is required.")

    elif step_key == "reviews":
        s = p.review_summary
        if s.overall_rating is not None and not (0 <= s.overall_rating <= 5):
            problems.append("Overall rating must be between 0 and 5.")
        if s.total_reviews is not None and s.total_reviews < 0:
            problems.append("Total review count cannot be negative.")
        counted = sum(v for v in s.breakdown().values() if v)
        if s.total_reviews and counted and counted > s.total_reviews:
            problems.append(
                f"The star breakdown adds up to {counted}, more than the "
                f"{s.total_reviews} total reviews."
            )
        for i, r in enumerate(p.reviews, start=1):
            if r.stars is not None and not (0 <= r.stars <= 5):
                problems.append(f"Review {i}: stars must be between 0 and 5.")

    return problems


def validate_profile(profile: SellerProfile) -> List[str]:
    """Every step's problems, in step order."""
    out = []
    for key in STEP_KEYS:
        out.extend(validate_step(profile, key))
    return out


def profile_status(profile: Optional[SellerProfile]) -> dict:
    """How far through onboarding this seller is, for the progress meter."""
    if profile is None:
        return {
            "started": False,
            "complete": False,
            "percent": 0,
            "steps_done": 0,
            "total_steps": len(STEPS),
            "step_problems": {k: ["Not started."] for k in STEP_KEYS},
            "gig_count": 0,
        }

    step_problems = {k: validate_step(profile, k) for k in STEP_KEYS}
    done = [k for k, v in step_problems.items() if not v]
    return {
        "started": _filled(profile.basic.name) or bool(profile.gigs),
        "complete": len(done) == len(STEP_KEYS),
        "percent": round(100 * len(done) / len(STEP_KEYS)),
        "steps_done": len(done),
        "total_steps": len(STEPS),
        "step_problems": step_problems,
        "gig_count": len(profile.gigs),
    }


# --- JSON schema for the vision model --------------------------------------

# Claude's structured-output mode takes a subset of JSON Schema: every
# property must be listed in `required`, `additionalProperties` must be false
# on every object, and validation keywords it does not implement (numeric and
# string bounds, patterns) are not honoured, so they are stripped rather than
# left in to imply a guarantee. Optional fields stay expressible because
# pydantic renders them as `anyOf: [..., {"type": "null"}]`, which is allowed
# -- so "listed as required" still means "may be null", which is exactly the
# behaviour the brief asks for.
_STRIPPED_KEYWORDS = {
    "default", "maxLength", "minLength", "maximum", "minimum",
    "exclusiveMaximum", "exclusiveMinimum", "maxItems", "minItems",
    "format", "pattern", "examples",
}


def _strictify(node):
    if isinstance(node, list):
        return [_strictify(n) for n in node]
    if not isinstance(node, dict):
        return node

    out = {k: _strictify(v) for k, v in node.items() if k not in _STRIPPED_KEYWORDS}
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}).keys())
    return out


def ocr_json_schema() -> dict:
    """The schema handed to the vision model.

    Generated from `ScreenshotReading` (the Fiverr-or-not gate wrapped around
    `SellerProfile`), never hand-written -- that is what stops the extractor
    and the form from drifting apart.
    """
    return _strictify(ScreenshotReading.model_json_schema())
