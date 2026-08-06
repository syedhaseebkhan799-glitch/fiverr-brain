"""
The onboarding wizard's logic: turning form strings into a typed profile,
blocking a step that isn't done, and surviving a browser close mid-way.

The Streamlit rendering is not tested here -- it has no logic left in it worth
testing. Everything that decides anything lives in profile_setup and schema,
and that is what these cover.
"""
import pytest

from src import documents, profile_setup as ps
from src.schema import FAQ, PACKAGE_TIERS, SellerProfile, validate_profile

FORM = {
    "name": "Syed Haseeb",
    "username": "SyedHaseeb",
    "profile_photo_url": "https://example.com/p.jpg",
    "country": "Pakistan",
    "languages": "English (fluent)\nUrdu (native)",
    "member_since": "Mar 2023",
    "avg_response_time": "1 hour",
    "headline": "AI Automation Engineer",
    "level": "Level 2",
    "bio": "I build AI automations that remove manual work.",
    "working_style": "Fast delivery, documented deliverables.",
    "skills": "n8n workflow automation\nPrompt engineering",
    "education": "BS Computer Science, NED University, 2023",
    "certifications": "OpenAI API Developer",
    "tests": "English (US) — Basic, 9/10",
    "overall_rating": "4.9",
    "total_reviews": "132",
    "stars_5": "120", "stars_4": "8", "stars_3": "2", "stars_2": "1", "stars_1": "1",
}

GIG_FORM = {
    "title": "I will build an n8n automation workflow",
    "category": "Programming & Tech",
    "description": "I design and build production-ready n8n workflows.",
    "extras": "Extra fast 24h delivery +$40",
}

PACKAGE_FORMS = {
    "basic": {"name": "Starter", "price": "$50", "delivery_days": "3",
              "revisions": "1", "features": "1 workflow\n3 nodes"},
    "standard": {"name": "Growth", "price": "150", "delivery_days": "5",
                 "revisions": "2", "features": "3 workflows"},
    "premium": {"name": "", "price": "", "delivery_days": "",
                "revisions": "", "features": ""},
}


def built_profile(**overrides):
    values = dict(FORM, **overrides)
    gig = ps.build_gig(
        GIG_FORM,
        packages=[ps.build_package(t, PACKAGE_FORMS[t]) for t in PACKAGE_TIERS],
        faqs=[FAQ(question="Do you provide support?", answer="Yes, 14 days.")],
    )
    return ps.build_profile(values, gigs=[gig])


# --- Coercion ---------------------------------------------------------------

def test_a_form_of_strings_becomes_a_typed_profile():
    profile = built_profile()
    assert profile.basic.name == "Syed Haseeb"
    assert profile.basic.languages == ["English (fluent)", "Urdu (native)"]
    assert profile.skills.skills == ["n8n workflow automation", "Prompt engineering"]
    assert profile.review_summary.overall_rating == 4.9
    assert profile.review_summary.total_reviews == 132
    assert profile.gigs[0].packages[0].price == 50.0
    assert profile.gigs[0].packages[0].delivery_days == 3


def test_a_price_with_a_currency_symbol_is_still_a_number():
    """A stray $ or comma should not become a validation error the seller has
    to decode."""
    assert ps.to_number("$1,250.50") == 1250.5
    assert ps.to_number("") is None
    assert ps.to_number("about fifty") is None
    assert ps.to_int("3 days") is None
    assert ps.to_int("3") == 3


def test_list_boxes_are_deduplicated_and_debulleted():
    assert ps.split_lines("- n8n\n\n* Prompt engineering\nn8n\n") == [
        "n8n", "Prompt engineering"
    ]


def test_a_blank_package_tier_is_not_saved_as_a_real_offer():
    """A nameless $0 premium package would show up in retrieval as something
    the seller offers."""
    profile = built_profile()
    tiers = [p.tier for p in profile.gigs[0].packages]
    assert tiers == ["basic", "standard"]


def test_an_empty_faq_row_is_dropped():
    gig = ps.build_gig(GIG_FORM, faqs=[FAQ(question="", answer="")])
    assert gig.faqs == []


def test_padded_packages_always_draws_three_tiers():
    profile = built_profile()
    padded = ps.padded_packages(profile.gigs[0])
    assert [p.tier for p in padded] == ["basic", "standard", "premium"]
    assert padded[2].price is None


def test_flatten_is_the_inverse_of_build():
    """The wizard reopens on a saved profile; the boxes have to come back
    filled with what was in them."""
    profile = built_profile()
    flat = ps.flatten_profile(profile)
    assert flat["name"] == "Syed Haseeb"
    assert flat["languages"] == ["English (fluent)", "Urdu (native)"]
    assert flat["overall_rating"] == 4.9


def test_the_seller_id_comes_from_the_username():
    assert built_profile().resolved_seller_id() == "syedhaseeb"


# --- Saving -----------------------------------------------------------------

def test_saving_persists_and_reloads(kb):
    seller_id = ps.save_profile(built_profile())
    loaded = ps.load_profile(seller_id)
    assert loaded.basic.name == "Syed Haseeb"
    assert loaded.gigs[0].packages[0].name == "Starter"


def test_an_invalid_profile_is_refused(kb):
    with pytest.raises(ValueError):
        ps.save_profile(built_profile(bio=""))
    assert ps.list_sellers() == []


def test_saving_writes_a_readable_markdown_export(kb):
    ps.save_profile(built_profile())
    exports = list(kb.glob("*.md"))
    assert len(exports) == 1
    text = exports[0].read_text(encoding="utf-8")
    assert "Syed Haseeb" in text
    assert "n8n automation workflow" in text


def test_the_export_cannot_escape_the_kb_folder(kb):
    """A seller_id is derived from a username the seller types."""
    profile = built_profile(username="../../evil")
    ps.save_profile(profile)
    written = list(kb.glob("*.md"))
    assert written and all(p.resolve().parent == kb.resolve() for p in written)


def test_a_readonly_kb_folder_does_not_fail_the_save(kb, monkeypatch):
    """The profile is already safely in SQLite by the time the export runs."""
    from pathlib import Path

    def deny(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "write_text", deny)
    seller_id = ps.save_profile(built_profile())
    assert ps.load_profile(seller_id) is not None


def test_deleting_a_profile_removes_the_export_too(kb):
    seller_id = ps.save_profile(built_profile())
    assert list(kb.glob("*.md"))
    assert ps.delete_profile(seller_id) is True
    assert not list(kb.glob("*.md"))
    assert ps.load_profile(seller_id) is None


def test_load_profile_without_an_id_returns_the_latest(kb):
    ps.save_profile(built_profile())
    second = built_profile(username="other", name="Other Person")
    ps.save_profile(second)
    assert ps.load_profile().resolved_seller_id() == "other"


# --- Status and per-step gating ---------------------------------------------

def test_status_on_an_empty_store_is_not_started(kb):
    assert ps.profile_status()["started"] is False
    assert ps.profile_status()["complete"] is False


def test_status_counts_completed_steps():
    status = ps.profile_status(built_profile())
    assert status["complete"] is True
    assert status["steps_done"] == status["total_steps"] == 6
    assert status["percent"] == 100


def test_status_names_the_steps_that_are_blocking():
    status = ps.profile_status(built_profile(bio="", skills=""))
    assert status["complete"] is False
    assert status["step_problems"]["about"]
    assert status["step_problems"]["skills"]
    assert not status["step_problems"]["basic"]


def test_a_profile_with_no_portfolio_or_reviews_is_still_complete():
    """Optional steps must not block a real seller who has neither yet."""
    profile = built_profile()
    profile.portfolio = []
    profile.reviews = []
    assert validate_profile(profile) == []


# --- Drafts -----------------------------------------------------------------

def test_a_draft_survives_and_reloads(kb):
    partial = ps.build_profile({"name": "Half done", "username": "half"})
    ps.save_draft(partial, step=2)

    loaded, step = ps.load_draft()
    assert step == 2
    assert loaded.basic.name == "Half done"
    # A draft is not a seller until it is saved.
    assert ps.list_sellers() == []


def test_clearing_a_draft(kb):
    ps.save_draft(built_profile(), step=1)
    ps.clear_draft()
    assert ps.load_draft() == (None, 0)


# --- Indexing ---------------------------------------------------------------

def test_apply_to_index_only_touches_this_seller(kb, brain):
    from src import config, ingest

    profile = built_profile(username="index_scope_test")
    try:
        ps.save_profile(profile)
        ps.apply_to_index(profile, brain)

        got = brain.client.get_collection(config.COLLECTION_NAME).get(
            where={"sellerId": "index_scope_test"}
        )
        assert got["ids"]
        # The shipped SOP layer must still be there.
        sops = brain.client.get_collection(config.COLLECTION_NAME).get(
            where={"layer": "sops"}
        )
        assert sops["ids"]
    finally:
        ingest.delete_seller_vectors("index_scope_test")
        brain.refresh_collection()


# --- Bio assist -------------------------------------------------------------

def test_bio_suggestion_fences_the_seller_answers(brain, monkeypatch):
    captured = {}

    def stub(prompt):
        captured["prompt"] = prompt
        return '"A bio."'

    monkeypatch.setattr(brain, "_call_llm", stub)
    assert ps.suggest_bio(brain, built_profile()) == "A bio."
    assert "SELLER_ANSWERS_START" in captured["prompt"]
    assert "Professional headline: AI Automation Engineer" in captured["prompt"]


def test_bio_suggestion_is_truncated_to_the_fiverr_limit(brain, monkeypatch):
    monkeypatch.setattr(brain, "_call_llm", lambda prompt: "y" * 5000)
    assert len(ps.suggest_bio(brain, built_profile())) == ps.MAX_BIO_CHARS


def test_bio_suggestion_refuses_an_empty_form(brain):
    with pytest.raises(ValueError):
        ps.suggest_bio(brain, SellerProfile())


@pytest.mark.parametrize("title,expected", [
    ("I will build n8n workflows!", "build_n8n_workflows"),
    ("AI  Influencer   Creation", "ai_influencer_creation"),
    ("", ""),
])
def test_slugify(title, expected):
    assert ps.slugify(title) == expected


# --- Migration from the pre-SQLite knowledge base ---------------------------

def _migration_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_kb_to_store.py"
    spec = importlib.util.spec_from_file_location("migrate_kb_to_store", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_GIG = """---
type: gig
gig_name: n8n Automation
category: Programming & Tech > Automations
---

# Gig: I will build AI-powered n8n automation workflows

## Tagline
Automation that runs while you sleep.

## What's delivered
- Custom workflows
- API integration

## Pricing tiers
| Tier | Price (PKR) | Delivery Time | Revisions |
|---|---|---|---|
| Basic | 11,667.42 | 2-day delivery | 1 Revision |
| Standard | 26,251.68 | 4-day delivery | 2 Revisions |
| Premium | 58,337.08 | 6-day delivery | No revisions included |
"""

LEGACY_PROFILE = """---
type: profile
---

# Seller Profile: Syed Haseeb

## Level
Level 2

## Response time
1 hour

## Specialties
- n8n automation
- Prompt engineering

## Languages
- English
"""


def test_migration_reads_the_real_legacy_format(kb):
    mig = _migration_module()
    (kb / "seller_profile.md").write_text(LEGACY_PROFILE, encoding="utf-8")
    (kb / "gig_n8n.md").write_text(LEGACY_GIG, encoding="utf-8")

    profile, sources = mig.build_profile_from_kb(kb)

    assert profile.basic.name == "Syed Haseeb"
    assert profile.basic.level == "Level 2"
    assert profile.basic.avg_response_time == "1 hour"
    assert profile.basic.languages == ["English"]
    assert profile.skills.skills == ["n8n automation", "Prompt engineering"]
    assert len(sources) == 2

    gig = profile.gigs[0]
    # "# Gig: " is a label in the file, not part of the buyer-facing title.
    assert gig.title == "I will build AI-powered n8n automation workflows"
    # The category lives in the frontmatter, not in a section.
    assert gig.category == "Programming & Tech > Automations"
    # Several headings feed the description; none of them is dropped.
    assert "Automation that runs while you sleep." in gig.description
    assert "Custom workflows" in gig.description


def test_migration_structures_the_pricing_table(kb):
    mig = _migration_module()
    (kb / "gig_n8n.md").write_text(LEGACY_GIG, encoding="utf-8")

    gig = mig.build_profile_from_kb(kb)[0].gigs[0]
    assert [p.tier for p in gig.packages] == ["basic", "standard", "premium"]
    assert gig.packages[0].price == 11667.42
    assert gig.packages[0].delivery_days == 2
    assert gig.packages[0].revisions == "1"
    assert gig.packages[2].revisions == "0"


def test_migration_records_the_currency_it_found(kb):
    """These prices are PKR. Converting them to USD would invent a number
    nobody can check against the source."""
    mig = _migration_module()
    (kb / "gig_n8n.md").write_text(LEGACY_GIG, encoding="utf-8")

    gig = mig.build_profile_from_kb(kb)[0].gigs[0]
    assert all(p.currency == "PKR" for p in gig.packages)


def test_migration_keeps_an_unparsable_pricing_box(kb):
    """An unstructured price is still worth something to a human reader."""
    mig = _migration_module()
    (kb / "gig_odd.md").write_text(
        "---\ntype: gig\n---\n\n# Gig: I will do a thing\n\n"
        "## Description\nA thing.\n\n"
        "## Pricing\nAsk me, it depends on scope.\n",
        encoding="utf-8",
    )
    gig = mig.build_profile_from_kb(kb)[0].gigs[0]
    assert gig.packages == []
    assert "Ask me, it depends on scope." in gig.description


def test_migration_on_an_empty_folder_is_not_an_error(kb):
    mig = _migration_module()
    assert mig.build_profile_from_kb(kb) == (None, [])


def test_migration_output_survives_a_save_and_reload(kb):
    mig = _migration_module()
    (kb / "seller_profile.md").write_text(LEGACY_PROFILE, encoding="utf-8")
    (kb / "gig_n8n.md").write_text(LEGACY_GIG, encoding="utf-8")

    profile, _ = mig.build_profile_from_kb(kb)
    # The legacy profile has no bio, so it is not complete -- importing it must
    # still work, or the migration would refuse to import real data.
    seller_id = ps.save_profile(profile, validate=False)

    loaded = ps.load_profile(seller_id)
    assert loaded.gigs[0].packages[1].price == 26251.68
    assert loaded.gigs[0].packages[1].currency == "PKR"


def test_migrated_content_becomes_retrievable_documents(kb):
    mig = _migration_module()
    (kb / "seller_profile.md").write_text(LEGACY_PROFILE, encoding="utf-8")
    (kb / "gig_n8n.md").write_text(LEGACY_GIG, encoding="utf-8")

    profile, _ = mig.build_profile_from_kb(kb)
    docs = documents.build_documents(profile)
    text = " ".join(d["text"] for d in docs)
    assert "11667.42 PKR" in text
    assert "n8n automation" in text
