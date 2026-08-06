"""
Schema and storage tests.

The schema is the one place the form, the OCR extractor and the database all
agree, so these cover the two things that would break that agreement: a
validation rule that only exists in one of them, and a round trip through
SQLite that quietly loses a field.
"""
import pytest

from src import store
from src.schema import (
    About, BasicInfo, FAQ, Gig, MAX_BIO_CHARS, MAX_SKILLS, Package,
    PortfolioItem, Review, ReviewSummary, SellerProfile, Skills, STEP_KEYS,
    derive_seller_id, ocr_json_schema, profile_status, validate_profile,
    validate_step,
)


def full_profile(**overrides) -> SellerProfile:
    profile = SellerProfile(
        basic=BasicInfo(
            name="Syed Haseeb", username="syedhaseeb",
            profile_photo_url="https://example.com/p.jpg", country="Pakistan",
            languages=["English (fluent)", "Urdu (native)"],
            member_since="Mar 2023", avg_response_time="1 hour",
            headline="AI Automation Engineer", level="Level 2",
        ),
        about=About(bio="I build AI automations that remove manual work.",
                    working_style="Fast delivery, documented deliverables."),
        skills=Skills(skills=["n8n workflow automation", "Prompt engineering"],
                      education=["BS Computer Science, NED University, 2023"],
                      certifications=["OpenAI API Developer"],
                      tests=["English (US) — Basic, 9/10"]),
        gigs=[Gig(
            title="I will build an n8n automation workflow",
            category="Programming & Tech",
            description="I design and build production-ready n8n workflows.",
            packages=[
                Package(tier="basic", name="Starter", price=50.0,
                        delivery_days=3, revisions="1",
                        features=["1 workflow", "3 nodes"]),
                Package(tier="standard", name="Growth", price=150.0,
                        delivery_days=5, revisions="2",
                        features=["3 workflows"]),
                Package(tier="premium", name="Scale", price=400.0,
                        delivery_days=10, revisions="unlimited",
                        features=["Unlimited workflows", "Support"]),
            ],
            extras=["Extra fast 24h delivery +$40"],
            faqs=[FAQ(question="Do you provide support?", answer="Yes, 14 days.")],
        )],
        portfolio=[PortfolioItem(title="Invoice automation",
                                 description="Cut a 4-hour task to 10 minutes.",
                                 image_url="https://example.com/i.png",
                                 link="https://example.com")],
        reviews=[Review(text="Delivered ahead of schedule.", stars=5.0,
                        buyer_country="United States", date="2 weeks ago")],
        review_summary=ReviewSummary(overall_rating=4.9, total_reviews=132,
                                     stars_5=120, stars_4=8, stars_3=2,
                                     stars_2=1, stars_1=1),
    )
    for key, value in overrides.items():
        setattr(profile, key, value)
    return profile


# --- Validation -------------------------------------------------------------

def test_a_complete_profile_validates():
    assert validate_profile(full_profile()) == []
    assert profile_status(full_profile())["complete"] is True


def test_every_step_key_is_validatable():
    """A step with no rule would silently always pass."""
    profile = SellerProfile()
    problems = {k: validate_step(profile, k) for k in STEP_KEYS}
    # Steps 5 and 6 are legitimately optional -- a seller with no portfolio and
    # no reviews yet is a real seller.
    assert problems["portfolio"] == [] and problems["reviews"] == []
    assert all(problems[k] for k in ("basic", "about", "skills", "gigs"))


@pytest.mark.parametrize("field", ["name", "username"])
def test_required_basic_fields_block_the_step(field):
    profile = full_profile()
    setattr(profile.basic, field, "")
    assert validate_step(profile, "basic")


def test_languages_are_required():
    profile = full_profile()
    profile.basic.languages = []
    assert validate_step(profile, "basic")


def test_bio_over_the_fiverr_limit_is_rejected():
    profile = full_profile()
    profile.about.bio = "x" * (MAX_BIO_CHARS + 1)
    problems = validate_step(profile, "about")
    assert problems and str(MAX_BIO_CHARS) in problems[0]


def test_too_many_skills_is_rejected():
    profile = full_profile()
    profile.skills.skills = [f"skill {i}" for i in range(MAX_SKILLS + 1)]
    assert validate_step(profile, "skills")


def test_a_gig_needs_a_title_and_a_description():
    profile = full_profile()
    profile.gigs[0].description = ""
    assert validate_step(profile, "gigs")


def test_duplicate_package_tiers_are_rejected():
    profile = full_profile()
    profile.gigs[0].packages[1].tier = "basic"
    assert any("basic" in p for p in validate_step(profile, "gigs"))


def test_a_half_filled_faq_is_rejected():
    profile = full_profile()
    profile.gigs[0].faqs = [FAQ(question="Do you?", answer="")]
    assert validate_step(profile, "gigs")


def test_star_breakdown_cannot_exceed_the_total():
    profile = full_profile()
    profile.review_summary.total_reviews = 5
    assert validate_step(profile, "reviews")


def test_an_out_of_range_rating_is_rejected():
    profile = full_profile()
    profile.review_summary.overall_rating = 7.0
    assert validate_step(profile, "reviews")


def test_unknown_package_tiers_are_dropped_not_kept():
    """A tier the model invented ('deluxe') must not reach the database as if
    it were a real Fiverr tier."""
    assert Package(tier="deluxe").tier is None
    assert Package(tier="  BASIC ").tier == "basic"


# --- Nullability on the OCR path -------------------------------------------

def test_every_field_is_optional_at_the_model_level():
    """A screenshot shows a fraction of a profile. The models have to be able
    to represent that without a validation error."""
    profile = SellerProfile()
    assert profile.basic.name is None
    assert profile.gigs == []
    assert profile.review_summary.overall_rating is None


def test_a_partial_extraction_validates_as_a_model_but_not_as_complete():
    partial = SellerProfile(basic=BasicInfo(name="Someone"), source_type="ocr")
    assert partial.source_type == "ocr"
    assert validate_profile(partial)  # not saveable yet, but representable


# --- Identity ---------------------------------------------------------------

def test_seller_id_prefers_the_username():
    assert derive_seller_id("SyedHaseeb", "Syed Haseeb") == "syedhaseeb"
    assert derive_seller_id(None, "Syed Haseeb") == "syed_haseeb"
    assert derive_seller_id(None, None) == "seller"


# --- The JSON schema handed to the vision model -----------------------------

def test_ocr_schema_is_strict_mode_compatible():
    """OpenAI's strict mode rejects a schema with optional properties or
    unlisted extras, and the whole point is that the extractor is bound to the
    same models the form uses."""
    schema = ocr_json_schema()

    def check(node, path="root"):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False, path
                assert set(node.get("required", [])) == set(
                    node.get("properties", {})
                ), path
            for key, value in node.items():
                assert key not in ("default", "maxLength", "minimum"), f"{path}.{key}"
                check(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                check(item, f"{path}[{i}]")

    check(schema)


def test_ocr_schema_covers_all_six_sections():
    props = ocr_json_schema()["properties"]
    for section in ("basic", "about", "skills", "gigs", "portfolio",
                    "reviews", "review_summary"):
        assert section in props


# --- Storage round trip -----------------------------------------------------

def test_profile_round_trips_through_sqlite():
    original = full_profile()
    seller_id = store.save_seller(original)
    loaded = store.load_seller(seller_id)

    assert loaded is not None
    assert loaded.basic.model_dump() == original.basic.model_dump()
    assert loaded.about.model_dump() == original.about.model_dump()
    assert loaded.skills.model_dump() == original.skills.model_dump()
    assert loaded.portfolio[0].model_dump() == original.portfolio[0].model_dump()
    assert loaded.reviews[0].model_dump() == original.reviews[0].model_dump()
    assert loaded.review_summary.model_dump() == original.review_summary.model_dump()

    gig, original_gig = loaded.gigs[0], original.gigs[0]
    assert gig.title == original_gig.title
    assert [p.tier for p in gig.packages] == ["basic", "standard", "premium"]
    assert gig.packages[2].revisions == "unlimited"
    assert gig.packages[0].features == ["1 workflow", "3 nodes"]
    assert gig.faqs[0].question == "Do you provide support?"
    assert gig.extras == ["Extra fast 24h delivery +$40"]


def test_resaving_replaces_rather_than_accumulates():
    profile = full_profile()
    store.save_seller(profile)
    profile.gigs = profile.gigs[:1]
    profile.gigs[0].packages = profile.gigs[0].packages[:1]
    store.save_seller(profile)

    loaded = store.load_seller(profile.resolved_seller_id())
    assert len(loaded.gigs) == 1
    assert len(loaded.gigs[0].packages) == 1


def test_deleting_a_seller_cascades():
    seller_id = store.save_seller(full_profile())
    assert store.delete_seller(seller_id) is True
    assert store.load_seller(seller_id) is None

    with store.connect() as conn:
        for table in ("gigs", "packages", "gig_faqs", "portfolio_items",
                      "reviews", "review_summary"):
            rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert rows == 0, f"{table} kept orphaned rows"


def test_sellers_are_independent():
    a = full_profile()
    b = full_profile()
    b.basic.username = "someoneelse"
    b.basic.name = "Someone Else"
    store.save_seller(a)
    store.save_seller(b)

    assert len(store.list_sellers()) == 2
    store.delete_seller(b.resolved_seller_id())
    assert store.load_seller(a.resolved_seller_id()) is not None


def test_loading_a_missing_seller_is_none_not_a_crash():
    assert store.load_seller("nobody") is None
    assert store.list_sellers() == []


# --- Drafts -----------------------------------------------------------------

def test_draft_round_trips_with_its_step():
    partial = SellerProfile(basic=BasicInfo(name="Half done"))
    store.save_draft(partial, step=2)

    loaded, step = store.load_draft()
    assert step == 2
    assert loaded.basic.name == "Half done"


def test_a_draft_can_be_invalid():
    """The whole point of a draft is that it is not finished yet."""
    store.save_draft(SellerProfile(), step=0)
    loaded, _ = store.load_draft()
    assert loaded is not None
    assert validate_profile(loaded)


def test_saving_a_draft_twice_overwrites_it():
    store.save_draft(SellerProfile(basic=BasicInfo(name="First")), step=1)
    store.save_draft(SellerProfile(basic=BasicInfo(name="Second")), step=3)
    loaded, step = store.load_draft()
    assert loaded.basic.name == "Second" and step == 3


def test_clearing_a_draft_works():
    store.save_draft(SellerProfile(), step=0)
    store.clear_draft()
    assert store.load_draft() == (None, 0)


def test_a_draft_from_an_older_schema_is_discarded_not_fatal():
    """A payload the current models cannot read must not brick the wizard."""
    store.init_db()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO drafts (draft_id, step, payload, updated_at)"
            " VALUES (?,?,?,?)",
            (store.DEFAULT_DRAFT_ID, 1, '{"nope": [1,2,3]}', "2026-01-01"),
        )
    assert store.load_draft() == (None, 0)


def test_a_draft_is_not_visible_as_a_seller():
    """A half-finished profile must never reach retrieval."""
    store.save_draft(full_profile(), step=1)
    assert store.list_sellers() == []


# --- gig_id uniqueness ------------------------------------------------------

def test_two_sellers_can_own_a_gig_with_the_same_id():
    """gig_id is a global primary key. An id carried in from an OCR
    extraction, or from a draft written under a different username, must not
    make the second seller's save fail with a raw SQLite error."""
    a = full_profile()
    b = full_profile()
    b.basic.username = "someoneelse"
    a.gigs[0].gig_id = "shared_id"
    b.gigs[0].gig_id = "shared_id"

    store.save_seller(a)
    store.save_seller(b)  # must not raise

    assert len(store.list_sellers()) == 2
    loaded_a = store.load_seller(a.resolved_seller_id())
    loaded_b = store.load_seller(b.resolved_seller_id())
    assert loaded_a.gigs[0].gig_id != loaded_b.gigs[0].gig_id


def test_two_gigs_with_the_same_title_get_distinct_ids():
    profile = full_profile()
    profile.gigs.append(profile.gigs[0].model_copy(deep=True))
    profile.gigs[1].gig_id = None
    profile.gigs[0].gig_id = None

    store.save_seller(profile)
    loaded = store.load_seller(profile.resolved_seller_id())
    assert len({g.gig_id for g in loaded.gigs}) == 2


def test_saving_writes_the_resolved_gig_ids_back_to_the_model():
    """The documents built from a just-saved profile have to carry the same
    gigId as the rows, or a citation points at a gig that is not there."""
    profile = full_profile()
    profile.gigs[0].gig_id = "not_namespaced"
    seller_id = store.save_seller(profile)

    assert profile.gigs[0].gig_id.startswith(f"{seller_id}__")
    assert profile.gigs[0].gig_id == store.load_seller(seller_id).gigs[0].gig_id


def test_a_gig_id_that_already_belongs_to_this_seller_is_kept():
    """Renaming a gig must not orphan its identity."""
    profile = full_profile()
    seller_id = store.save_seller(profile)
    original_id = profile.gigs[0].gig_id

    profile.gigs[0].title = "I will do something completely different"
    store.save_seller(profile)
    assert store.load_seller(seller_id).gigs[0].gig_id == original_id
