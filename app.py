"""
Fiverr Brain -- Streamlit chat UI.
Run with: streamlit run app.py
"""
import streamlit as st

from src.rag import FiverrBrain
from src import logging_utils
from src.modes import new_gig, optimize, onboarding, buyer_reply

st.set_page_config(page_title="Fiverr Brain", page_icon="🧠", layout="centered")

st.title("🧠 Fiverr Brain")
st.caption("Internal assistant for your Fiverr business — gigs, policies, and SOPs.")

# --- Init brain once per session ---
if "brain" not in st.session_state:
    try:
        st.session_state.brain = FiverrBrain()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

brain = st.session_state.brain

# --- Sidebar: mode selector ---
with st.sidebar:
    st.header("Mode")
    mode = st.radio(
        "Choose a mode",
        ["Ask a question", "/new-gig", "/optimize", "/onboarding", "/buyer-reply"],
    )
    st.divider()
    st.caption("Knowledge base layers: profile & gigs, policies, SOPs.")
    if st.button("🔄 Rebuild index"):
        from src import ingest
        with st.spinner("Reindexing knowledge base..."):
            n = ingest.build_index(verbose=False)
        st.success(f"Reindexed {n} chunks.")

# --- Render chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Mode-specific inputs ---
placeholder = "Ask about your gigs, pricing, policies, or SOPs..."
if mode == "/new-gig":
    placeholder = "Describe the new gig idea (e.g. 'a gig for Zapier automations')"
elif mode == "/optimize":
    placeholder = "Which gig should I optimize? (e.g. 'the AI influencer gig')"
elif mode == "/onboarding":
    placeholder = "Ask an onboarding question (e.g. 'how do I handle a revision request?')"
elif mode == "/buyer-reply":
    placeholder = "Paste the buyer's message here"

user_input = st.chat_input(placeholder)

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            if mode == "Ask a question":
                result = brain.ask(user_input)
                answer = result["answer"]
                if result["sources"]:
                    answer += f"\n\n*Sources: {', '.join(result['sources'])}*"
                logging_utils.log_query(
                    user_input, result["answer"], result["sources"], result["chunks_used"]
                )
            elif mode == "/new-gig":
                answer = new_gig.run(brain, user_input)
            elif mode == "/optimize":
                answer = optimize.run(brain, user_input)
            elif mode == "/onboarding":
                answer = onboarding.run(brain, trainee="demo_trainee", question=user_input)
            elif mode == "/buyer-reply":
                answer = buyer_reply.run(brain, user_input)
            else:
                answer = "Unknown mode."

        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
