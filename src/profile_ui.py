"""
Streamlit rendering for profile onboarding.

Six numbered steps with a progress indicator, validation that blocks advancing
out of a step, and a draft written on every step change so closing the browser
mid-way costs nothing.

Kept out of app.py so the wizard's widget plumbing doesn't drown the chat loop.
All the reading, writing and validating lives in profile_setup and schema --
this module only draws it.

Widget state is the working copy. Streamlit stores every keyed widget in
`st.session_state`, so the scalar steps read straight back out of it, and the
three repeatable sections (gigs, portfolio, reviews) keep a list in session
state alongside. Deleting row 2 of 5 therefore has to drop the widget keys for
rows 2..5 as well, or Streamlit would redraw the deleted row's text against the
row that moved up.
"""
import streamlit as st

from . import config, ingest, profile_setup as ps
from .rag import EmbeddingError, LLMError
from .schema import FAQ, PACKAGE_TIERS, STEPS, format_number

PREFIX = "wiz_"

# Widgets for the repeatable rows live under their own namespace. Removing a
# row means dropping every widget key beneath a prefix, and without the
# separation `wiz_gig...` would also match the `wiz_gigs` list itself and
# delete the data the widgets are about to be re-seeded from.
WIDGET = f"{PREFIX}w_"

STEP_KEY = f"{PREFIX}step"
GIGS_KEY = f"{PREFIX}gigs"
PORTFOLIO_KEY = f"{PREFIX}portfolio"
REVIEWS_KEY = f"{PREFIX}reviews"
SELLER_KEY = f"{PREFIX}seller_id"
EDITING_KEY = f"{PREFIX}editing"
# Which seller the widgets currently hold. Compared against the selector to
# decide whether a reload is needed; without it the wizard would re-read the
# database on every rerun and throw away whatever the user had just typed.
LOADED_SELLER_KEY = f"{PREFIX}loaded_seller"
DISMISSED_DRAFT_KEY = f"{PREFIX}draft_dismissed"

NEW_SELLER_LABEL = "➕ New seller"


# --- Session state ---------------------------------------------------------

def _blank_gig() -> dict:
    return {
        "gig_id": None, "title": "", "category": "", "description": "",
        "extras": "",
        "packages": {t: {f.key: "" for f in ps.PACKAGE_FIELDS}
                     for t in PACKAGE_TIERS},
        "faqs": [],
    }


def _gig_to_state(gig) -> dict:
    packages = {}
    for pkg in ps.padded_packages(gig):
        packages[pkg.tier] = {
            "name": pkg.name or "",
            "price": format_number(pkg.price),
            "currency": pkg.currency or "",
            "delivery_days": "" if pkg.delivery_days is None else str(pkg.delivery_days),
            "revisions": pkg.revisions or "",
            "features": "\n".join(pkg.features),
        }
    return {
        "gig_id": gig.gig_id,
        "title": gig.title or "",
        "category": gig.category or "",
        "description": gig.description or "",
        "extras": "\n".join(gig.extras),
        "packages": packages,
        "faqs": [{"question": f.question or "", "answer": f.answer or ""}
                 for f in gig.faqs],
    }


def _load_into_state(profile):
    """Seed every widget from a stored or drafted profile."""
    _clear_state()
    for key, value in ps.flatten_profile(profile).items():
        st.session_state[f"{PREFIX}{key}"] = (
            "\n".join(str(v) for v in value) if isinstance(value, list)
            else ("" if value is None else str(value))
        )
    st.session_state[GIGS_KEY] = [_gig_to_state(g) for g in profile.gigs]
    st.session_state[PORTFOLIO_KEY] = [
        {f.key: getattr(item, f.key) or "" for f in ps.PORTFOLIO_FIELDS}
        for item in profile.portfolio
    ]
    st.session_state[REVIEWS_KEY] = [
        {"text": r.text or "", "stars": format_number(r.stars),
         "buyer_country": r.buyer_country or "", "date": r.date or ""}
        for r in profile.reviews
    ]
    st.session_state[SELLER_KEY] = profile.resolved_seller_id()


def _clear_state():
    """Empty the form. The wizard's own controls are not form content and
    survive -- clearing the seller selector would reset the choice that caused
    the clear, and the wizard would flip back and forth on every rerun."""
    protected = {STEP_KEY, EDITING_KEY, LOADED_SELLER_KEY, DISMISSED_DRAFT_KEY}
    for key in [k for k in st.session_state if k.startswith(PREFIX)]:
        if key not in protected:
            del st.session_state[key]


def _drop_keys(prefix: str):
    """Forget every widget under a prefix so it re-seeds from the list."""
    for key in [k for k in st.session_state if k.startswith(prefix)]:
        del st.session_state[key]


def _ensure_state():
    st.session_state.setdefault(STEP_KEY, 0)
    st.session_state.setdefault(GIGS_KEY, [])
    st.session_state.setdefault(PORTFOLIO_KEY, [])
    st.session_state.setdefault(REVIEWS_KEY, [])
    st.session_state.setdefault(SELLER_KEY, None)


# --- Widgets ---------------------------------------------------------------

def _widget(field, key, initial="", label=None):
    """Draw one Field bound to `key` and return its current value."""
    if key not in st.session_state:
        if field.kind == "list":
            value = "\n".join(str(v) for v in initial) if isinstance(initial, (list, tuple)) \
                else str(initial or "")
        else:
            value = "" if initial is None else str(initial)
        st.session_state[key] = value

    label = (label or field.label) + (" *" if field.required else "")

    if field.kind == "select":
        options = [""] + list(field.options)
        current = st.session_state[key]
        index = options.index(current) if current in options else 0
        return st.selectbox(label, options, index=index, key=key, help=field.help)

    if field.kind in ("textarea", "list"):
        value = st.text_area(
            label, key=key, help=field.help, placeholder=field.placeholder,
            height=140 if field.kind == "textarea" else 120,
        )
        if field.max_chars:
            used = len(value or "")
            colour = "red" if used > field.max_chars else "gray"
            st.caption(f":{colour}[{used}/{field.max_chars} characters]")
        if field.max_items:
            count = len(ps.split_lines(value))
            colour = "red" if count > field.max_items else "gray"
            st.caption(f":{colour}[{count}/{field.max_items} entries]")
        return value

    return st.text_input(
        label, key=key, help=field.help, placeholder=field.placeholder
    )


def _text(key, label, initial=""):
    """A plain text input seeded once, then owned by session state.

    Passing both `value=` and `key=` on a rerun makes Streamlit overwrite what
    the user just typed, so the initial value is written into session state
    instead and the widget is bound by key alone.
    """
    st.session_state.setdefault(key, str(initial or ""))
    return st.text_input(label, key=key)


def _scalar_values() -> dict:
    """Everything from the four non-repeatable steps."""
    fields = (ps.BASIC_FIELDS + ps.ABOUT_FIELDS + ps.SKILLS_FIELDS
              + ps.REVIEW_SUMMARY_FIELDS)
    return {f.key: st.session_state.get(f"{PREFIX}{f.key}", "") for f in fields}


def _sync_gigs():
    """Pull widget values back into the gig list."""
    for i, gig in enumerate(st.session_state[GIGS_KEY]):
        base = f"{WIDGET}gig{i}_"
        for f in ps.GIG_FIELDS:
            gig[f.key] = st.session_state.get(f"{base}{f.key}", gig.get(f.key, ""))
        for tier in PACKAGE_TIERS:
            pkg = gig["packages"].setdefault(tier, {})
            for f in ps.PACKAGE_FIELDS:
                pkg[f.key] = st.session_state.get(
                    f"{base}pkg_{tier}_{f.key}", pkg.get(f.key, "")
                )
        for j, faq in enumerate(gig["faqs"]):
            faq["question"] = st.session_state.get(f"{base}faq{j}_q", faq["question"])
            faq["answer"] = st.session_state.get(f"{base}faq{j}_a", faq["answer"])


def _sync_rows(state_key, fields, prefix):
    for i, row in enumerate(st.session_state[state_key]):
        for f in fields:
            row[f.key] = st.session_state.get(
                f"{WIDGET}{prefix}{i}_{f.key}", row.get(f.key, "")
            )


def collect_profile():
    """The current form state as a SellerProfile."""
    _sync_gigs()
    _sync_rows(PORTFOLIO_KEY, ps.PORTFOLIO_FIELDS, "port")
    _sync_rows(REVIEWS_KEY, ps.REVIEW_FIELDS, "rev")

    gigs = []
    for g in st.session_state[GIGS_KEY]:
        packages = [ps.build_package(tier, g["packages"].get(tier, {}))
                    for tier in PACKAGE_TIERS]
        faqs = [FAQ(question=f["question"], answer=f["answer"]) for f in g["faqs"]]
        gigs.append(ps.build_gig(g, packages=packages, faqs=faqs,
                                 gig_id=g.get("gig_id")))

    return ps.build_profile(
        _scalar_values(),
        gigs=gigs,
        portfolio=[ps.build_portfolio_item(r) for r in st.session_state[PORTFOLIO_KEY]],
        reviews=[ps.build_review(r) for r in st.session_state[REVIEWS_KEY]],
        seller_id=st.session_state.get(SELLER_KEY),
    )


# --- Steps -----------------------------------------------------------------

def _render_scalar_step(fields, brain=None, bio_helper=False):
    for field in fields:
        _widget(field, f"{PREFIX}{field.key}")
        if bio_helper and field.key == "bio":
            if st.button(":material/auto_awesome: Draft my bio from the answers above", key="draft_bio"):
                try:
                    with st.spinner("Drafting..."):
                        bio = ps.suggest_bio(brain, collect_profile())
                    st.session_state[f"{PREFIX}bio"] = bio
                    st.rerun()
                except (LLMError, ValueError) as e:
                    st.warning(str(e))


def _render_gigs_step():
    gigs = st.session_state[GIGS_KEY]
    st.caption(
        "One block per gig. Each gig carries its own Basic / Standard / Premium "
        "packages, extras and FAQs — leave a package blank if you don't offer it."
    )

    if not gigs:
        st.info("No gigs yet. Add your first one below.")

    for i, gig in enumerate(gigs):
        title = gig.get("title") or f"Gig {i + 1}"
        with st.expander(f":material/description: {title}", expanded=len(gigs) == 1):
            base = f"{WIDGET}gig{i}_"
            for f in ps.GIG_FIELDS:
                _widget(f, f"{base}{f.key}", gig.get(f.key, ""))

            st.markdown("**Pricing packages**")
            for tier, col in zip(PACKAGE_TIERS, st.columns(3)):
                with col:
                    st.markdown(f"*{tier.capitalize()}*")
                    for f in ps.PACKAGE_FIELDS:
                        _widget(f, f"{base}pkg_{tier}_{f.key}",
                                gig["packages"].get(tier, {}).get(f.key, ""),
                                label=f.label)

            st.markdown("**FAQs**")
            for j, faq in enumerate(gig["faqs"]):
                c1, c2, c3 = st.columns([4, 5, 1])
                with c1:
                    _text(f"{base}faq{j}_q", "Question", faq["question"])
                with c2:
                    _text(f"{base}faq{j}_a", "Answer", faq["answer"])
                with c3:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("✕", key=f"{base}faq{j}_del", help="Remove this FAQ"):
                        _sync_gigs()
                        gig["faqs"].pop(j)
                        _drop_keys(f"{base}faq")
                        st.rerun()

            c1, c2 = st.columns(2)
            with c1:
                if st.button(":material/add: Add an FAQ", key=f"{base}add_faq"):
                    _sync_gigs()
                    gig["faqs"].append({"question": "", "answer": ""})
                    st.rerun()
            with c2:
                if st.button(":material/delete: Remove this gig", key=f"{base}del"):
                    _sync_gigs()
                    gigs.pop(i)
                    _drop_keys(f"{WIDGET}gig")
                    st.rerun()

    if st.button(":material/add: Add a gig"):
        _sync_gigs()
        gigs.append(_blank_gig())
        st.rerun()


def _render_row_step(state_key, fields, prefix, blank, singular):
    rows = st.session_state[state_key]
    if not rows:
        st.info(f"No {singular}s added. This step is optional — you can skip it.")

    for i, row in enumerate(rows):
        label = row.get("title") or row.get("text") or f"{singular.capitalize()} {i + 1}"
        with st.expander(f"{label[:60]}", expanded=len(rows) == 1):
            for f in fields:
                _widget(f, f"{WIDGET}{prefix}{i}_{f.key}", row.get(f.key, ""))
            if st.button(f":material/delete: Remove this {singular}", key=f"{WIDGET}{prefix}{i}_del"):
                _sync_rows(state_key, fields, prefix)
                rows.pop(i)
                _drop_keys(f"{WIDGET}{prefix}")
                st.rerun()

    if st.button(f":material/add: Add a {singular}", key=f"{WIDGET}{prefix}_add"):
        _sync_rows(state_key, fields, prefix)
        rows.append(dict(blank))
        st.rerun()


def _render_reviews_step():
    st.markdown("**Overall rating**")
    cols = st.columns(2)
    for f, col in zip(ps.REVIEW_SUMMARY_FIELDS[:2], cols):
        with col:
            _widget(f, f"{PREFIX}{f.key}")

    st.markdown("**Star breakdown**")
    for f, col in zip(ps.REVIEW_SUMMARY_FIELDS[2:], st.columns(5)):
        with col:
            _widget(f, f"{PREFIX}{f.key}")

    st.divider()
    st.markdown("**Individual reviews**")
    _render_row_step(
        REVIEWS_KEY, ps.REVIEW_FIELDS, "rev",
        {"text": "", "stars": "", "buyer_country": "", "date": ""}, "review",
    )


def _render_step(step_key, brain):
    if step_key == "basic":
        _render_scalar_step(ps.BASIC_FIELDS)
    elif step_key == "about":
        _render_scalar_step(ps.ABOUT_FIELDS, brain=brain, bio_helper=True)
    elif step_key == "skills":
        _render_scalar_step(ps.SKILLS_FIELDS)
    elif step_key == "gigs":
        _render_gigs_step()
    elif step_key == "portfolio":
        _render_row_step(
            PORTFOLIO_KEY, ps.PORTFOLIO_FIELDS, "port",
            {f.key: "" for f in ps.PORTFOLIO_FIELDS}, "project",
        )
    elif step_key == "reviews":
        _render_reviews_step()


# --- Saving ----------------------------------------------------------------

def save_and_index(brain, profile):
    """Persist, then index. Never report success before retrieval can see it."""
    try:
        seller_id = ps.save_profile(profile)
    except (ValueError, OSError) as e:
        st.error(f"Could not save your profile: {e}")
        return None

    warnings = []
    try:
        with st.spinner("Updating the knowledge base index..."):
            ps.apply_to_index(profile, brain, warn=warnings.append)
    except ingest.RebuildInProgress:
        st.warning(
            "Saved, but another rebuild is running so the index wasn't updated. "
            "Use **Rebuild index** under Maintenance in the sidebar once it finishes."
        )
        return seller_id
    except EmbeddingError as e:
        st.warning(f"Saved, but the index could not be updated: {e}")
        return seller_id
    except Exception as e:
        st.warning(
            f"Saved to the profile database, but the index update failed: "
            f"`{type(e).__name__}: {e}`\n\nRun `python scripts/reindex.py` to fix it."
        )
        return seller_id

    ps.clear_draft()
    st.success(
        f"Profile saved and indexed as `{seller_id}`. The brain now answers "
        f"from it."
    )
    for w in warnings:
        st.warning(w)
    if config.is_ephemeral_host():
        st.info(
            "This host resets its filesystem on restart. To keep this profile, "
            "run the same setup locally, commit `data/` and `kb/`, and push."
        )
    return seller_id


# --- Public entry points ---------------------------------------------------

def render(brain):
    """Draw the whole six-step onboarding wizard."""
    _ensure_state()

    # The page title and breadcrumb are drawn by the shell in app.py.
    _render_loader()

    profile = collect_profile()
    status = ps.profile_status(profile)
    step_index = max(0, min(st.session_state[STEP_KEY], len(STEPS) - 1))
    step = STEPS[step_index]

    st.progress(
        status["percent"] / 100,
        text=f"Step {step['number']} of {len(STEPS)} · "
             f"{status['steps_done']}/{status['total_steps']} steps complete",
    )
    st.caption(" · ".join(
        f"{':material/check_circle:' if not status['step_problems'][s['key']] else ':material/radio_button_unchecked:'}"
        f" {s['number']}. {s['title']}"
        for s in STEPS
    ))

    st.subheader(f"{step['number']}. {step['title']}")
    st.caption(step["help"])

    _render_step(step["key"], brain)

    # Re-collect: the widgets above may have changed since the top of the run.
    profile = collect_profile()
    problems = ps.validate_step(profile, step["key"])

    st.divider()
    back, nxt, save = st.columns([1, 1, 2])

    with back:
        if st.button("← Back", disabled=step_index == 0, use_container_width=True):
            ps.save_draft(profile, step_index)
            st.session_state[STEP_KEY] = step_index - 1
            st.rerun()

    with nxt:
        last = step_index == len(STEPS) - 1
        if st.button("Next →", disabled=last or bool(problems),
                     use_container_width=True):
            ps.save_draft(profile, step_index + 1)
            st.session_state[STEP_KEY] = step_index + 1
            st.rerun()

    with save:
        blocking = ps.validate_profile(profile)
        if st.button(":material/save: Save profile & index", type="primary",
                     disabled=bool(blocking), use_container_width=True):
            if save_and_index(brain, profile):
                st.session_state[SELLER_KEY] = profile.resolved_seller_id()

    if problems:
        st.markdown("**Before moving on:**")
        for problem in problems:
            st.caption(f":red[• {problem}]")

    if st.button(":material/save: Save draft and come back later"):
        ps.save_draft(profile, step_index)
        st.success("Draft saved. It will be waiting when you reopen this page.")

    remaining = [
        f"{s['number']}. {s['title']}" for s in STEPS
        if status["step_problems"][s["key"]]
    ]
    if remaining:
        st.caption("Steps still incomplete: " + ", ".join(remaining))
    else:
        st.success("All six steps are complete — press **Save profile & index**.")

    _render_danger_zone(brain)


def _render_loader():
    """The seller selector and the draft-resume offer.

    Drawn on every rerun, not only the first: a selector that disappears after
    one pass leaves a seller with two profiles unable to reach the second one.
    The reload is guarded on the selection actually having changed, so it never
    overwrites what the user is in the middle of typing.
    """
    sellers = ps.list_sellers()

    if sellers:
        options = {f"{s['name'] or s['seller_id']} ({s['gig_count']} gig(s))":
                   s["seller_id"] for s in sellers}
        # The saved seller is the default, not "new". Opening a blank form on
        # an existing profile invites the seller to type it all in again and
        # end up with two of themselves.
        label = st.selectbox(
            "Editing profile", list(options) + [NEW_SELLER_LABEL],
            key=EDITING_KEY,
            help="Every seller is stored separately and answered separately.",
        )
        selected = options.get(label)

        if selected != st.session_state.get(LOADED_SELLER_KEY):
            st.session_state[LOADED_SELLER_KEY] = selected
            existing = ps.load_profile(selected) if selected else None
            if existing is not None:
                _load_into_state(existing)
            else:
                _clear_state()
                st.session_state[SELLER_KEY] = None
                st.session_state[STEP_KEY] = 0
            st.rerun()

    draft, draft_step = ps.load_draft()
    if draft is None or st.session_state.get(DISMISSED_DRAFT_KEY):
        return

    st.info("You have an unfinished profile draft.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(":material/history: Resume the draft", use_container_width=True):
            st.session_state[DISMISSED_DRAFT_KEY] = True
            # The draft is what the widgets now hold. Marking it loaded stops
            # the selector reloading the stored seller straight over the top.
            st.session_state[LOADED_SELLER_KEY] = draft.resolved_seller_id()
            _load_into_state(draft)
            st.session_state[STEP_KEY] = draft_step
            st.rerun()
    with c2:
        if st.button(":material/delete: Discard it and start fresh", use_container_width=True):
            ps.clear_draft()
            st.session_state[DISMISSED_DRAFT_KEY] = True
            st.rerun()


def _render_danger_zone(brain):
    seller_id = st.session_state.get(SELLER_KEY)
    if not seller_id or not ps.load_profile(seller_id):
        return
    with st.expander(":material/warning: Delete this seller"):
        st.caption(
            f"Removes `{seller_id}` from the profile database, deletes the "
            f"markdown export, and drops their vectors from the index."
        )
        if st.checkbox("I want to delete this seller", key=f"{PREFIX}confirm_del"):
            if st.button(":material/delete_forever: Delete permanently"):
                ps.delete_profile(seller_id)
                ps.remove_from_index(seller_id, brain)
                _clear_state()
                st.session_state[STEP_KEY] = 0
                st.session_state[LOADED_SELLER_KEY] = None
                st.session_state.pop(EDITING_KEY, None)
                st.success(f"Deleted `{seller_id}`.")
                st.rerun()


def render_seller_picker():
    """Sidebar seller selector. Returns the selected seller id, or None.

    Retrieval is filtered by this: with two sellers in the store, an unscoped
    question would answer from whichever one happened to be nearest.
    """
    sellers = ps.list_sellers()
    if not sellers:
        return None
    if len(sellers) == 1:
        return sellers[0]["seller_id"]

    options = {f"{s['name'] or s['seller_id']}": s["seller_id"] for s in sellers}
    label = st.selectbox(
        "Answering as", list(options),
        help="Questions are answered from this seller's profile only. "
             "Policies and SOPs are shared.",
    )
    return options[label]
