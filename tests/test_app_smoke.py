"""
Does the app actually render?

Every other test exercises logic behind the UI. These run `app.py` itself
through Streamlit's own harness, which is the only way to catch the class of
mistake that never reaches a unit test: a widget key collision, a session-state
value written after the widget was drawn, a `st.columns` count mismatch, an
exception inside a rendering branch nobody imported.

Nothing here spends money. Almost every test walks a form, which makes no API
call at all; the one test that does send a message stubs the brain first.
"""
import pytest

from src import config, profile_setup as ps, store
from src.schema import About, BasicInfo, Gig, Package, SellerProfile, Skills

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

TIMEOUT = 120


def run_app(**session_state):
    at = AppTest.from_file("app.py", default_timeout=TIMEOUT)
    for key, value in session_state.items():
        at.session_state[key] = value
    return at.run()


def seeded_profile(seller_id="smoke_seller") -> SellerProfile:
    return SellerProfile(
        seller_id=seller_id,
        basic=BasicInfo(name="Smoke Tester", username=seller_id,
                        country="Pakistan", languages=["English (fluent)"]),
        about=About(bio="I build automations."),
        skills=Skills(skills=["n8n"]),
        gigs=[Gig(gig_id="g1", title="I will build a workflow",
                  description="Production-ready workflows.",
                  packages=[Package(tier="basic", name="Starter", price=50.0,
                                    delivery_days=3, revisions="1",
                                    features=["1 workflow"])])],
    )


def assert_no_exceptions(at):
    if at.exception:
        messages = "\n".join(str(e.value) for e in at.exception)
        raise AssertionError(f"app raised while rendering:\n{messages}")


# --- Boot -------------------------------------------------------------------

def test_the_app_boots():
    at = run_app()
    assert_no_exceptions(at)
    # The name lives in the sidebar rail's masthead, the way the Hub does it.
    assert any("Fiverr Brain" in m.value for m in at.sidebar.markdown)


def test_a_missing_api_key_is_an_actionable_message_not_a_traceback(monkeypatch):
    import streamlit as st

    # load_brain is @st.cache_resource, and the cache outlives a single
    # AppTest run -- without clearing it the app would reuse the brain another
    # test already built and never reach the missing-key branch.
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    st.cache_resource.clear()
    try:
        at = run_app()
        assert_no_exceptions(at)
        assert any("OPENAI_API_KEY" in e.value for e in at.error)
    finally:
        st.cache_resource.clear()


def test_every_mode_renders_without_raising():
    """A mode that crashes on selection is invisible until someone clicks it."""
    for mode in ["👤 Profile onboarding", "🖼️ Import from screenshot",
                 "Ask a question", "/new-gig", "/optimize", "/onboarding",
                 "/buyer-reply"]:
        at = run_app(mode=mode)
        assert_no_exceptions(at)


# --- The shell ---------------------------------------------------------------

def test_the_header_names_the_page_you_are_on():
    """The breadcrumb is the only thing telling you which mode is active once
    the big per-screen headers are gone."""
    at = run_app(mode="/buyer-reply")
    assert_no_exceptions(at)
    assert any("Buyer reply" in m.value for m in at.markdown)


def test_an_empty_chat_offers_example_questions():
    at = run_app(mode="Ask a question")
    assert_no_exceptions(at)
    assert any(b.label == "What do my gigs cost?" for b in at.button)


def test_clicking_an_example_asks_it(kb, monkeypatch):
    """The examples are the front door -- if the click does not become a
    question, the empty state is decoration.

    This is the one smoke test that sends a message, so the brain is stubbed:
    patching the class reaches the instance `st.cache_resource` is holding.
    """
    from src.rag import FiverrBrain

    monkeypatch.setattr(
        FiverrBrain, "ask",
        lambda self, question, **kwargs: {
            "answer": f"stubbed answer to: {question}",
            "sources": [], "chunks_used": 0, "citations": [],
        },
    )

    at = run_app(mode="Ask a question")
    example = next(b for b in at.button if b.label == "What do my gigs cost?")
    at = example.click().run()

    assert_no_exceptions(at)
    assert at.session_state.messages, "the click produced no exchange"
    assert at.session_state.messages[0]["content"] == "What do my gigs cost?"


def test_the_rail_shows_who_the_answers_are_about(kb):
    ps.save_profile(seeded_profile("rail_seller"), validate=False)
    at = run_app(mode="Ask a question")
    assert_no_exceptions(at)
    assert any("Smoke Tester" in m.value for m in at.sidebar.markdown)


# --- The wizard -------------------------------------------------------------

def test_the_wizard_opens_on_step_one():
    at = run_app(mode="👤 Profile onboarding")
    assert_no_exceptions(at)
    assert any("1. Basic information" in h.value for h in at.subheader)


def test_the_wizard_blocks_next_until_the_step_is_valid():
    at = run_app(mode="👤 Profile onboarding")
    assert_no_exceptions(at)
    nxt = next(b for b in at.button if b.label == "Next →")
    assert nxt.disabled, "an empty first step must not advance"


def test_filling_step_one_unblocks_next():
    at = run_app(mode="👤 Profile onboarding")
    at.text_input(key="wiz_name").set_value("Smoke Tester")
    at.text_input(key="wiz_username").set_value("smoketester")
    at.text_area(key="wiz_languages").set_value("English (fluent)")
    at = at.run()

    assert_no_exceptions(at)
    assert not next(b for b in at.button if b.label == "Next →").disabled


def test_advancing_saves_a_draft(kb):
    at = run_app(mode="👤 Profile onboarding")
    at.text_input(key="wiz_name").set_value("Draft Tester")
    at.text_input(key="wiz_username").set_value("drafttester")
    at.text_area(key="wiz_languages").set_value("English")
    at = at.run()

    next(b for b in at.button if b.label == "Next →").click().run()

    saved, step = store.load_draft()
    assert saved is not None and saved.basic.name == "Draft Tester"
    assert step == 1
    # A draft is not a seller.
    assert store.list_sellers() == []


def test_each_of_the_six_steps_renders(kb):
    """Steps 4-6 draw repeatable rows and column layouts that steps 1-3 do
    not, so booting on step 1 alone proves very little."""
    for index in range(6):
        at = run_app(mode="👤 Profile onboarding", wiz_step=index)
        assert_no_exceptions(at)


def test_adding_a_gig_renders_three_package_columns(kb):
    at = run_app(mode="👤 Profile onboarding", wiz_step=3)
    at = next(b for b in at.button if b.label == ":material/add: Add a gig").click().run()

    assert_no_exceptions(at)
    for tier in ("basic", "standard", "premium"):
        assert at.text_input(key=f"wiz_w_gig0_pkg_{tier}_price") is not None


def test_adding_an_faq_row_renders(kb):
    at = run_app(mode="👤 Profile onboarding", wiz_step=3)
    at = next(b for b in at.button if b.label == ":material/add: Add a gig").click().run()
    at = next(b for b in at.button if b.label == ":material/add: Add an FAQ").click().run()

    assert_no_exceptions(at)
    assert at.text_input(key="wiz_w_gig0_faq0_q") is not None


def test_a_stored_profile_reopens_with_its_values(kb):
    ps.save_profile(seeded_profile(), validate=False)
    at = run_app(mode="👤 Profile onboarding")
    assert_no_exceptions(at)
    assert at.text_input(key="wiz_name").value == "Smoke Tester"


def test_a_complete_profile_enables_save(kb):
    profile = seeded_profile()
    ps.save_profile(profile, validate=False)
    at = run_app(mode="👤 Profile onboarding")
    assert_no_exceptions(at)

    save = next(b for b in at.button if b.label == ":material/save: Save profile & index")
    assert not save.disabled


# --- Screenshot import ------------------------------------------------------

def test_the_import_screen_renders_its_upload_area():
    at = run_app(mode="🖼️ Import from screenshot")
    assert_no_exceptions(at)

    text = " ".join(m.value for m in at.markdown)
    assert "Screenshot import" in text
    # The Fiverr-only rule is the feature; it has to be stated before upload,
    # not discovered by being refused.
    assert "Fiverr screenshots only" in text


def test_the_import_review_screen_renders_an_extraction(kb):
    """The review screen is the whole point of the feature and is only
    reachable after a successful extraction, so it is the branch most likely
    to rot unnoticed."""
    from src import ocr, ocr_ui

    profile = seeded_profile("ocr_smoke")
    profile.source_type = "ocr"
    at = run_app(**{
        "mode": "🖼️ Import from screenshot",
        ocr_ui.EXTRACTED_KEY: profile,
        ocr_ui.REPORT_KEY: ocr.confidence_report(profile),
        ocr_ui.FILENAME_KEY: "screenshot.png",
    })

    assert_no_exceptions(at)
    assert any("Check what was read" in h.value for h in at.subheader)


def test_a_low_confidence_extraction_says_so_rather_than_offering_a_save(kb):
    from src import ocr, ocr_ui

    empty = SellerProfile(seller_id="nothing_read", source_type="ocr")
    report = ocr.confidence_report(empty)
    assert report["low_confidence"] is True

    at = run_app(**{
        "mode": "🖼️ Import from screenshot",
        ocr_ui.EXTRACTED_KEY: empty,
        ocr_ui.REPORT_KEY: report,
        ocr_ui.FILENAME_KEY: "blurry.png",
    })

    assert_no_exceptions(at)
    assert any("very little back" in e.value for e in at.error)


# --- Sidebar ----------------------------------------------------------------

def test_the_seller_picker_appears_only_with_more_than_one_seller(kb):
    ps.save_profile(seeded_profile("seller_one"), validate=False)
    at = run_app(mode="Ask a question")
    assert_no_exceptions(at)
    assert not any("Answering as" in s.label for s in at.sidebar.selectbox)

    second = seeded_profile("seller_two")
    second.basic.name = "Second Seller"
    ps.save_profile(second, validate=False)

    at = run_app(mode="Ask a question")
    assert_no_exceptions(at)
    assert any("Answering as" in s.label for s in at.sidebar.selectbox)


def test_an_estimated_threshold_is_disclosed(monkeypatch):
    """Running the refusal boundary on a guess is workable; hiding that it is
    a guess is not."""
    monkeypatch.setattr(config, "MAX_DISTANCE_IS_ESTIMATED", True)
    at = run_app()
    assert_no_exceptions(at)
    assert any("estimate" in i.value for i in at.info)


def test_the_seller_selector_stays_available_across_reruns(kb):
    """It used to render only on the first pass, which left a seller with two
    profiles unable to reach the second one."""
    ps.save_profile(seeded_profile("selector_a"), validate=False)
    second = seeded_profile("selector_b")
    second.basic.name = "Second Seller"
    second.gigs[0].gig_id = None
    ps.save_profile(second, validate=False)

    at = run_app(mode="👤 Profile onboarding")
    assert_no_exceptions(at)
    assert any(s.label == "Editing profile" for s in at.selectbox)

    # A rerun that changes nothing must not make the selector disappear.
    at = at.run()
    assert_no_exceptions(at)
    assert any(s.label == "Editing profile" for s in at.selectbox)


def test_editing_a_seller_does_not_reload_over_what_you_typed(kb):
    """The reload is guarded on the selection changing. Without that guard the
    form re-reads the database on every rerun and discards live edits."""
    ps.save_profile(seeded_profile("edit_guard"), validate=False)

    at = run_app(mode="👤 Profile onboarding")
    assert at.text_input(key="wiz_name").value == "Smoke Tester"

    at.text_input(key="wiz_name").set_value("Renamed Mid-Edit")
    at = at.run()

    assert_no_exceptions(at)
    assert at.text_input(key="wiz_name").value == "Renamed Mid-Edit"


def test_switching_to_new_seller_clears_the_form(kb):
    ps.save_profile(seeded_profile("switch_test"), validate=False)

    at = run_app(mode="👤 Profile onboarding")
    assert at.text_input(key="wiz_name").value == "Smoke Tester"

    at.selectbox(key="wiz_editing").set_value("➕ New seller")
    at = at.run()

    assert_no_exceptions(at)
    assert at.text_input(key="wiz_name").value == ""
