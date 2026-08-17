"""
Fiverr Brain -- Streamlit chat UI.
Run with: streamlit run app.py

The shell is modelled on the Silverthread Labs Hub: a rail on the left holding
the brand and the nav, a breadcrumb and status pills across the top of the page,
and thin-bordered panels below, in either a dark or a light appearance. All of
that lives in src/theme.py -- this file decides *what* is on the page, never
what colour it is.
"""
import streamlit as st

from src import config, logging_utils, ocr_ui, profile_setup, profile_ui, theme
from src.rag import EmbeddingError, FiverrBrain, LLMError
from src.modes import new_gig, optimize, onboarding, buyer_reply

PROFILE_MODE = "👤 Profile onboarding"
OCR_MODE = "🖼️ Import from screenshot"

# Mode values are the app's internal names and are matched by string elsewhere,
# so they are kept exactly as they were. Only the *display* changes here.
MODES = [
    "Ask a question",
    "/new-gig",
    "/optimize",
    "/buyer-reply",
    "/onboarding",
    PROFILE_MODE,
    OCR_MODE,
]

# Material Symbols, not emoji. Streamlit renders `:material/name:` in any label
# it treats as markdown, and the result is a single-colour line icon that
# inherits the text colour -- so an inactive row's icon is grey and the active
# row's icon turns green with its label, which is what the Hub's rail does.
# Emoji cannot do that: they carry their own colours and differ per platform.
NAV_LABELS = {
    "Ask a question": ":material/forum: Ask the brain",
    "/new-gig": ":material/add_circle: New gig",
    "/optimize": ":material/trending_up: Optimize a gig",
    "/buyer-reply": ":material/mail: Buyer reply",
    "/onboarding": ":material/school: Team onboarding",
    PROFILE_MODE: ":material/person: Seller profile",
    OCR_MODE: ":material/image: Screenshot import",
}

PAGES = {
    "Ask a question": (
        "Ask the brain",
        "Answers are built only from your saved profile, gigs, policies and SOPs.",
    ),
    "/new-gig": ("New gig", "Draft a new gig from what already works for you."),
    "/optimize": ("Optimize a gig", "Tighten an existing gig's title, pricing and copy."),
    "/buyer-reply": ("Buyer reply", "Draft a reply to a buyer in your own voice."),
    "/onboarding": ("Team onboarding", "Walk a new team member through your SOPs."),
    PROFILE_MODE: ("Seller profile", "Six steps. Nothing is indexed until you save."),
    OCR_MODE: ("Screenshot import", "Fiverr screenshots only — anything else is refused."),
}

EXAMPLES = [
    "What do my gigs cost?",
    "How do I handle a revision request?",
    "Which gig should I promote this week?",
]

PENDING_KEY = "pending_question"

BOT_AVATAR = ":material/psychology:"
USER_AVATAR = ":material/person:"

st.set_page_config(page_title="Fiverr Brain", page_icon="🧠", layout="wide")
theme.inject()


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

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar: the rail -------------------------------------------------------
with st.sidebar:
    theme.brand("Fiverr Brain", "SILVERTHREAD LABS")

    # A screen that wants to hand off to another mode leaves the request in
    # pending_mode, and it is applied here, before the radio is built. The radio
    # owns `mode`, and Streamlit raises on any write to a widget's key once the
    # widget exists -- so the handoff has to land ahead of it, not from inside
    # the screen that asked for it.
    if ocr_ui.PENDING_MODE_KEY in st.session_state:
        st.session_state.mode = st.session_state.pop(ocr_ui.PENDING_MODE_KEY)

    # First visit of a session lands on onboarding until the profile is set up.
    # After that the radio owns the value, so a seller who deliberately switches
    # away with an incomplete profile isn't dragged back on every rerun.
    if "mode" not in st.session_state:
        st.session_state.mode = (
            "Ask a question"
            if profile_setup.profile_status()["complete"]
            else PROFILE_MODE
        )
    mode = st.radio(
        "Navigation",
        MODES,
        key="mode",
        format_func=lambda m: NAV_LABELS.get(m, m),
        label_visibility="collapsed",
    )

    st.divider()

    # Which seller every answer is grounded in. Shown only when there is more
    # than one, so the common single-seller case stays uncluttered.
    seller_id = profile_ui.render_seller_picker()

    trainee = "demo_trainee"
    if mode == "/onboarding":
        theme.section("Trainee")
        trainee = st.text_input("Trainee name", value="demo_trainee").strip() or "demo_trainee"
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

    if st.button(":material/delete_sweep: Clear chat", use_container_width=True):
        st.session_state.messages = []
        brain.reset_history()
        st.rerun()

    # Maintenance is for whoever runs the app, not for whoever uses it, so it
    # is folded away rather than sitting in the nav.
    with st.expander(":material/settings: Maintenance"):
        st.caption("Knowledge base layers: profile & gigs, policies, SOPs.")

        if st.button(":material/refresh: Rebuild index", use_container_width=True):
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

        gaps = logging_utils.get_unanswered_questions()
        st.caption(f":material/help: Knowledge gaps: {len(gaps)}")
        if gaps:
            for g in gaps[-15:]:
                st.markdown(f"- {g['question']}")

    st.divider()

    # Appearance sits with the rail's other quiet controls, above the account
    # card. Flipping it reruns the script, and theme.inject() at the top of the
    # file has already run with the new value by then.
    theme.section("Appearance")
    theme.switch()

    st.divider()
    status = profile_setup.profile_status()
    profile = profile_setup.load_profile(seller_id) if seller_id else None
    if profile is not None:
        username = profile.basic.username or profile.resolved_seller_id()
        theme.account_card(
            profile.basic.name or username,
            f"@{username} · {status['gig_count']} gig(s)",
        )
    else:
        theme.account_card("No seller yet", "Start in Seller profile")

# --- Page header -------------------------------------------------------------
page_title, page_subtitle = PAGES.get(mode, (mode, ""))

if status["complete"]:
    pills = theme.pill("✓ Profile complete", "ok")
else:
    pills = theme.pill(
        f"Profile {status['steps_done']}/{status['total_steps']}", "warn"
    )
pills += " " + theme.pill(f"{status['gig_count']} gig(s)", "mute")

theme.page_header("Fiverr Brain", page_title, page_subtitle, pills)

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

# --- These two are forms, not chats: render and stop here ---
if mode == PROFILE_MODE:
    profile_ui.render(brain)
    st.stop()

if mode == OCR_MODE:
    ocr_ui.render(brain)
    st.stop()

# --- Render chat history ---
for msg in st.session_state.messages:
    avatar = BOT_AVATAR if msg["role"] == "assistant" else USER_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# An empty chat is the app's front door. A blank page there teaches nobody what
# to type, so it offers three questions that are one click away.
if not st.session_state.messages and mode == "Ask a question":
    theme.note(
        "<b>Ask anything about your Fiverr business.</b><br>"
        "Every answer is built from your own profile, gigs, policies and SOPs — "
        "never from the open internet. If the knowledge base does not cover it, "
        "the brain says so instead of guessing."
    )
    st.write("")
    for col, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        with col:
            if st.button(example, use_container_width=True, key=f"ex_{example}"):
                st.session_state[PENDING_KEY] = example
                st.rerun()

# --- Mode-specific inputs ---
PLACEHOLDERS = {
    "Ask a question": "Ask about your gigs, pricing, policies, or SOPs...",
    "/new-gig": "Describe the new gig idea (e.g. 'a gig for Zapier automations')",
    "/optimize": "Which gig should I optimize? (e.g. 'the AI influencer gig')",
    "/onboarding": "Ask an onboarding question (e.g. 'how do I handle a revision request?')",
    "/buyer-reply": "Paste the buyer's message here",
}

raw_input_text = st.chat_input(PLACEHOLDERS[mode])

# A clicked example is the same as a typed question from here on.
if not raw_input_text and PENDING_KEY in st.session_state:
    raw_input_text = st.session_state.pop(PENDING_KEY)

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

    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(user_input)

    answer = None
    sources = []
    citations = []
    chunks_used = 0

    with st.chat_message("assistant", avatar=BOT_AVATAR):
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
            with st.expander(
                    f":material/description: {len(citations)} source chunk(s) used"):
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
