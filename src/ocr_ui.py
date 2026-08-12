"""
Streamlit rendering for the screenshot import.

Upload -> extract -> review -> confirm. The review screen is the point of the
feature: the model read an image, and the person who owns the profile is the
only one who can say whether it read it correctly. Nothing reaches the database
or the index until they press confirm.

Fields that came back null are shown as blanks with a note saying they were not
visible, rather than being hidden. A hidden blank looks like a field that does
not exist; a visible one is an invitation to fill it in.
"""
import streamlit as st

from . import ocr, profile_setup as ps, profile_ui
from .rag import fence

EXTRACTED_KEY = "ocr_extracted"
REPORT_KEY = "ocr_report"
FILENAME_KEY = "ocr_filename"


def _reset():
    for key in (EXTRACTED_KEY, REPORT_KEY, FILENAME_KEY):
        st.session_state.pop(key, None)


def _render_upload():
    st.caption(
        "Drop in a screenshot of your Fiverr profile or a gig page. It is read "
        "by an AI vision model, shown to you for checking, and only saved once "
        "you confirm it. Images only, up to "
        f"{ocr.config.MAX_UPLOAD_BYTES // 1_048_576} MB — location data is "
        "stripped before the image is sent. **Only Fiverr screenshots are "
        "accepted** — anything else is refused without being extracted."
    )

    uploaded = st.file_uploader(
        "Screenshot",
        type=["png", "jpg", "jpeg", "webp", "gif", "bmp"],
        accept_multiple_files=False,
    )
    if uploaded is None:
        return

    data = uploaded.getvalue()
    try:
        ocr.validate_image(data, uploaded.name)
    except ocr.OCRError as e:
        st.error(str(e))
        return

    st.image(data, caption=uploaded.name, use_container_width=True)

    if st.button("🔍 Read this screenshot", type="primary"):
        try:
            with st.spinner("Reading the screenshot..."):
                profile, report = ocr.extract(data, uploaded.name)
        except ocr.NotFiverrError as e:
            # The one refusal that is about the picture, not the pipeline:
            # the model looked and it simply is not Fiverr.
            st.error(f"🚫 {e}")
            return
        except ocr.OCRError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(
                f"Reading the screenshot failed: `{type(e).__name__}: {e}`\n\n"
                "Try again, or enter the profile manually."
            )
            return

        st.session_state[EXTRACTED_KEY] = profile
        st.session_state[REPORT_KEY] = report
        st.session_state[FILENAME_KEY] = uploaded.name
        st.rerun()


def _render_report(report):
    found = report["sections_found"]
    missing = report["sections_missing"]

    if report.get("image_shows"):
        st.caption(f"The model recognised this as: *{report['image_shows']}*")

    st.metric(
        "Fields read from the image",
        f"{report['populated']} of {report['total']}",
        help="Everything else came back empty because it was not visible.",
    )

    if report["low_confidence"]:
        st.error(
            f"**This screenshot gave very little back** — only "
            f"{report['populated']} of {report['total']} fields were readable. "
            f"That usually means the image is cropped, blurry, or shows a "
            f"Fiverr page with little profile detail on it.\n\n"
            f"Saving this would put a mostly-empty profile into your knowledge "
            f"base, which makes the brain answer worse, not better. Either "
            f"upload a clearer screenshot, or fill the profile in yourself in "
            f"**👤 Profile onboarding**."
        )
    elif missing:
        st.warning(
            "Read from the image: " + ", ".join(found) + ".\n\n"
            "Not visible, so left blank: " + ", ".join(missing) + ". "
            "Fill in whatever matters before saving."
        )
    else:
        st.success("All six sections had something readable in this screenshot.")


def _render_review(brain):
    profile = st.session_state[EXTRACTED_KEY]
    report = st.session_state[REPORT_KEY]

    st.subheader("Check what was read")
    st.caption(
        f"From `{st.session_state.get(FILENAME_KEY, 'the screenshot')}`. "
        "Nothing has been saved yet. Correct anything that is wrong — the model "
        "was told to leave a field blank rather than guess, so blanks are "
        "expected."
    )

    _render_report(report)
    st.divider()

    existing = ps.load_profile(profile.resolved_seller_id())
    merge = False
    if existing is not None:
        merge = st.checkbox(
            f"Merge into the existing profile `{existing.resolved_seller_id()}` "
            f"instead of replacing it",
            value=True,
            help="Merging keeps what you already entered and only fills in or "
                 "updates what this screenshot shows.",
        )

    with st.expander("📄 What the model extracted, field by field", expanded=False):
        st.json(profile.model_dump(exclude_none=False))

    st.markdown("**Send it to the onboarding form to edit and save**")
    st.caption(
        "The form is the only path into the knowledge base — the same "
        "validation, the same six steps, the same save. This just pre-fills it."
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ Open in the onboarding form", type="primary",
                     use_container_width=True):
            final = ocr.merge_into(existing, profile) if merge else profile
            profile_ui._load_into_state(final)
            st.session_state[profile_ui.STEP_KEY] = 0
            # The extraction is what the wizard's widgets now hold. Marking it
            # loaded stops the seller selector reloading the stored profile
            # straight over the top of it on the next rerun.
            st.session_state[profile_ui.LOADED_SELLER_KEY] = (
                final.resolved_seller_id()
            )
            st.session_state[profile_ui.DISMISSED_DRAFT_KEY] = True
            ps.save_draft(final, 0)
            _reset()
            st.session_state.mode = "👤 Profile onboarding"
            st.rerun()

    with c2:
        if st.button("🗑️ Discard and try another screenshot",
                     use_container_width=True):
            _reset()
            st.rerun()

    if report["low_confidence"]:
        st.caption(
            ":red[This extraction is flagged low-confidence. Opening it in the "
            "form is still allowed — but check every field before you save.]"
        )


def render(brain):
    st.header("🖼️ Import from a screenshot")

    if EXTRACTED_KEY in st.session_state:
        _render_review(brain)
    else:
        _render_upload()

    st.divider()
    st.caption(
        "Nothing is fetched from fiverr.com. Data enters this app only through "
        "the onboarding form or a screenshot you upload yourself."
    )


def summarise_for_prompt(profile) -> str:
    """OCR'd text is untrusted -- it is whatever was written in someone's
    screenshot. Any path that puts it in front of the model fences it first."""
    return fence(profile.model_dump_json(exclude_none=True), "screenshot_extract")
