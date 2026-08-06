"""
Fiverr Brain -- Streamlit chat UI.
Run with: streamlit run app.py
"""
import streamlit as st

from src import config, logging_utils, ocr_ui, profile_setup, profile_ui
from src.rag import EmbeddingError, FiverrBrain, LLMError
from src.modes import new_gig, optimize, onboarding, buyer_reply

PROFILE_MODE = "👤 Profile onboarding"
OCR_MODE = "🖼️ Import from screenshot"

st.set_page_config(page_title="Fiverr Brain", page_icon="🧠", layout="centered")

st.title("🧠 Fiverr Brain")
st.caption("Internal assistant for your Fiverr business — gigs, policies, and SOPs.")


@st.cache_resource(show_spinner="Loading the brain (first run downloads the embedding model)...")
def load_brain():
    """Cached across sessions -- one embedding model for the whole container."""
    return FiverrBrain()


# --- Init brain once per container ---
try:
    brain = load_brain()
except RuntimeError as e:
    # Missing/invalid API key -- actionable, show the message as-is.
    st.error(str(e))
    st.stop()
except Exception as e:
    # Model download failure, corrupt vector store, etc. Never show a traceback.
    st.error(
        "Fiverr Brain could not start.\n\n"
        f"**Details:** `{type(e).__name__}: {e}`\n\n"
        "Try reloading the page. If it keeps failing, rebuild the index locally "
        "with `python scripts/reindex.py` and redeploy."
    )
    st.stop()

if brain.index_warning:
    st.warning(brain.index_warning)

if config.MAX_DISTANCE_IS_ESTIMATED:
    # The refusal boundary is what stops the brain answering from irrelevant
    # chunks. Running on an unmeasured estimate is workable but the user
    # should know, rather than discovering it through a strange answer.
    st.info(
        f"Relevance threshold `MAX_DISTANCE={config.MAX_DISTANCE}` is an "
        f"estimate for the **{config.EMBEDDING_PROVIDER}** embeddings, not a "
        f"measurement. Run `python scripts/check_threshold.py` once and set "
        f"`MAX_DISTANCE` in your `.env` to what it suggests."
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar ---
with st.sidebar:
    st.header("Mode")
    MODES = [
        PROFILE_MODE,
        OCR_MODE,
        "Ask a question",
        "/new-gig",
        "/optimize",
        "/onboarding",
        "/buyer-reply",
    ]
    # First visit of a session lands on onboarding until the profile is set up.
    # After that the radio owns the value, so a seller who deliberately switches
    # away with an incomplete profile isn't dragged back on every rerun.
    if "mode" not in st.session_state:
        st.session_state.mode = (
            "Ask a question"
            if profile_setup.profile_status()["complete"]
            else PROFILE_MODE
        )
    mode = st.radio("Choose a mode", MODES, key="mode")

    st.divider()
    profile_ui.render_sidebar_status()
    # Which seller every answer is grounded in. Shown only when there is more
    # than one, so the common single-seller case stays uncluttered.
    seller_id = profile_ui.render_seller_picker()
    st.divider()
    trainee = "demo_trainee"
    if mode == "/onboarding":
        trainee = st.text_input("Trainee name", value="demo_trainee").strip() or "demo_trainee"
        st.caption("Onboarding steps")
        for item in onboarding.get_progress(trainee):
            done = st.checkbox(
                item["step"],
                value=item["done"],
                key=f"step_{trainee}_{item['step']}",
            )
            if done and not item["done"]:
                onboarding.mark_step_complete(trainee, item["step"])
                st.rerun()
            elif not done and item["done"]:
                onboarding.unmark_step(trainee, item["step"])
                st.rerun()
        st.divider()

    st.caption("Knowledge base layers: profile & gigs, policies, SOPs.")

    if st.button("🔄 Rebuild index"):
        from src import ingest
        warnings = []
        try:
            with st.spinner("Reindexing knowledge base..."):
                n = ingest.build_index(verbose=False, warn=warnings.append)
                brain.refresh_collection()
        except ingest.RebuildInProgress as e:
            st.info(str(e))
            n = None
        except EmbeddingError as e:
            st.error(f"Reindex failed, your existing index is unchanged.\n\n{e}")
            n = None
        except Exception as e:
            st.error(f"Reindex failed, your existing index is unchanged.\n\n`{e}`")
            n = None
        if n is not None:
            if n:
                st.success(f"Reindexed {n} chunks.")
                if config.is_ephemeral_host():
                    st.info(
                        "This host resets its filesystem on restart. To make the "
                        "change permanent, run `python scripts/reindex.py` locally, "
                        "commit `data/chroma_db/`, and push."
                    )
            else:
                st.warning("Nothing indexed — no readable .md files found in kb/.")
            for w in warnings:
                st.warning(w)

    if st.button("🗑️ Clear chat"):
        st.session_state.messages = []
        brain.reset_history()
        st.rerun()

    st.divider()
    gaps = logging_utils.get_unanswered_questions()
    with st.expander(f"❓ Knowledge gaps ({len(gaps)})"):
        if not gaps:
            st.caption("No unanswered questions logged yet.")
        else:
            st.caption("Questions the KB could not answer — consider adding content.")
            for g in gaps[-15:]:
                st.markdown(f"- {g['question']}")

# --- These two are forms, not chats: render and stop here ---
if mode == PROFILE_MODE:
    profile_ui.render(brain)
    st.stop()

if mode == OCR_MODE:
    ocr_ui.render(brain)
    st.stop()

# --- Render chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Mode-specific inputs ---
PLACEHOLDERS = {
    "Ask a question": "Ask about your gigs, pricing, policies, or SOPs...",
    "/new-gig": "Describe the new gig idea (e.g. 'a gig for Zapier automations')",
    "/optimize": "Which gig should I optimize? (e.g. 'the AI influencer gig')",
    "/onboarding": "Ask an onboarding question (e.g. 'how do I handle a revision request?')",
    "/buyer-reply": "Paste the buyer's message here",
}

raw_input_text = st.chat_input(PLACEHOLDERS[mode])

if raw_input_text:
    user_input = raw_input_text.strip()

    if not user_input:
        st.warning("Please type a question — empty messages are ignored.")
        st.stop()

    if len(user_input) > config.MAX_INPUT_CHARS:
        st.warning(
            f"Your message is {len(user_input):,} characters. Only the first "
            f"{config.MAX_INPUT_CHARS:,} will be used."
        )
        user_input = user_input[: config.MAX_INPUT_CHARS]

    with st.chat_message("user"):
        st.markdown(user_input)

    answer = None
    sources = []
    citations = []
    chunks_used = 0

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                if mode == "Ask a question":
                    result = brain.ask(user_input, seller_id=seller_id)
                elif mode == "/new-gig":
                    result = new_gig.run(brain, user_input, seller_id=seller_id)
                elif mode == "/optimize":
                    result = optimize.run(brain, user_input, seller_id=seller_id)
                elif mode == "/onboarding":
                    result = onboarding.run(brain, trainee=trainee, question=user_input)
                elif mode == "/buyer-reply":
                    result = buyer_reply.run(brain, user_input, seller_id=seller_id)
                else:
                    result = {"answer": "Unknown mode.", "sources": [],
                              "chunks_used": 0, "citations": []}

                answer = result["answer"]
                sources = result["sources"]
                chunks_used = result["chunks_used"]
                citations = result.get("citations", [])

            except (LLMError, EmbeddingError) as e:
                answer = f"⚠️ {e}"
            except Exception as e:
                answer = (
                    f"⚠️ Something went wrong: `{type(e).__name__}: {e}`\n\n"
                    "Try again, or rebuild the index from the sidebar."
                )

        display = answer
        if sources:
            display += f"\n\n*Sources: {', '.join(sources)}*"
        st.markdown(display)

        # The chunks the answer was actually built from. Filenames say which
        # document; this says which sentences, so a claim can be checked.
        if citations:
            with st.expander(f"📎 {len(citations)} source chunk(s) used"):
                for c in citations:
                    label = c["source"]
                    if c["sectionType"] not in ("unknown", c["layer"]):
                        label += f" · {c['sectionType']}"
                    if c["sourceType"] == "ocr":
                        label += " · read from a screenshot"
                    st.markdown(f"**{label}**")
                    st.text(c["text"])
                    st.divider()

    # Only commit the exchange to history once we actually have a reply,
    # so a failed call can't leave a dangling user message.
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.messages.append({"role": "assistant", "content": display})

    logging_utils.log_query(user_input, answer, sources, chunks_used, mode=mode)
