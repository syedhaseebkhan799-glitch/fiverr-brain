"""
The Silverthread Labs Hub look, applied to Streamlit -- in dark and in light.

Everything visual lives here, and every colour lives in `PALETTES`: two dicts
with identical keys, one per appearance. Nothing else in the app names a colour,
so `mode()` is the only switch there is and restyling can never break
behaviour.

A theme is painted in two layers, and they are kept in step by hand:

*   `.streamlit/config.toml` paints what Streamlit draws for itself and this
    module never reaches -- dropdown popovers, alert tints, code blocks, the
    focus rings. It holds the light palette under `[theme]` and the dark one
    under `[theme.dark]`, and the *browser* chooses between them from the
    reader's system preference.
*   This module paints everything else, keyed off `mode()`.

On a fresh visit the two layers agree, because `mode()` starts from
`st.context.theme.type` -- which appearance Streamlit actually rendered. If the
reader then flips the in-app switch, this module has to win the disagreement on
its own, which is why the handful of rules that fight a Streamlit-set colour
carry `!important`. Everywhere else the cascade is left alone.

Streamlit's DOM is not a public contract, so every selector here is written to
fail *soft*: if a future release renames something, the rule stops applying and
the widget falls back to its own theme's appearance -- which is still readable,
because config.toml gave that theme the same colours. Nothing here is
load-bearing for using the app -- which is why, for instance, the nav's radio
dots are hidden by matching the element that actually contains the `input`
rather than by guessing at child order. A browser without `:has()` shows the
dots; a wrong guess would have hidden the labels.

The one rule that is *not* safe to broaden is the font. Streamlit renders its
chevrons as Material icon ligatures, so a font-family applied widely enough to
reach them replaces every arrow in the app with the literal word
"keyboard_arrow_right". The stack is therefore set on the document and the icon
font is pinned back by name.
"""
import streamlit as st

# --- The palettes, read off the Hub -----------------------------------------
#
# Both dicts carry the same keys, and `_css` reads them by name only, so a new
# colour has to be added to both or the app fails loudly at import-time-ish
# (the first `KeyError` on a rerun) rather than silently rendering one theme
# with a hole in it. `_check_palettes` below makes that failure immediate.
#
# The light palette is not the dark one inverted. Depth is inverted instead: a
# dark page lifts panels *towards* the light, a light page seats them on a
# faintly grey ground and keeps the panels white. Green also darkens, because
# the Hub's #22C55E is a 1.8:1 contrast against white and unreadable as text.

DARK = {
    "scheme": "dark",           # CSS color-scheme: native scrollbars, controls
    "bg": "#0A0A0A",            # page
    "sidebar": "#0C0C0C",       # nav rail, separated from the page by a border
    "card": "#0E0E0E",          # panels, barely lifted off the page
    "raised": "#141414",        # hover states and inputs
    "code": "#141414",          # preformatted blocks
    "border": "#1F1F1F",        # the thin lines that define every panel
    "hairline": "#171717",      # internal dividers, quieter than a border
    "text": "#EDEDED",
    "muted": "#8A8A8A",
    "shadow": "none",           # a dark page has no light to cast one
    "accent": "#22C55E",        # the Hub's green: active nav, positives, focus
    "accent_soft": "rgba(34, 197, 94, 0.10)",
    "accent_line": "rgba(34, 197, 94, 0.30)",
    "accent_ink": "#06180E",    # text on a filled green button
    "accent_hover": "#1EA855",
    "danger": "#F87171",
    "danger_soft": "rgba(248, 113, 113, 0.10)",
    "danger_line": "rgba(248, 113, 113, 0.35)",
    "warn": "#EAB308",
    "warn_soft": "rgba(234, 179, 8, 0.10)",
    "warn_line": "rgba(234, 179, 8, 0.35)",
    "info": "#60A5FA",
    "info_soft": "rgba(96, 165, 250, 0.10)",
    "info_line": "rgba(96, 165, 250, 0.35)",
}

LIGHT = {
    "scheme": "light",
    "bg": "#F7F8F8",
    "sidebar": "#FCFCFD",
    "card": "#FFFFFF",
    "raised": "#F1F2F4",
    "code": "#F4F5F7",
    "border": "#E3E5E8",
    "hairline": "#ECEEF0",
    "text": "#16181D",
    "muted": "#5F6875",
    "shadow": "0 1px 2px rgba(16, 24, 40, 0.04)",
    "accent": "#15803D",
    "accent_soft": "rgba(21, 128, 61, 0.08)",
    "accent_line": "rgba(21, 128, 61, 0.28)",
    "accent_ink": "#FFFFFF",
    "accent_hover": "#14532D",
    "danger": "#B91C1C",
    "danger_soft": "rgba(185, 28, 28, 0.07)",
    "danger_line": "rgba(185, 28, 28, 0.26)",
    "warn": "#92400E",
    "warn_soft": "rgba(180, 83, 9, 0.08)",
    "warn_line": "rgba(180, 83, 9, 0.26)",
    "info": "#1D4ED8",
    "info_soft": "rgba(29, 78, 216, 0.07)",
    "info_line": "rgba(29, 78, 216, 0.24)",
}

PALETTES = {"dark": DARK, "light": LIGHT}
MODES = ("dark", "light")
DEFAULT_MODE = "dark"


def _check_palettes():
    """Fail on a half-added colour rather than shipping one broken theme."""
    missing = set(DARK) ^ set(LIGHT)
    if missing:
        raise RuntimeError(
            "theme.DARK and theme.LIGHT must carry the same keys; these are in "
            f"one but not the other: {sorted(missing)}"
        )


_check_palettes()

# Segoe UI on Windows, San Francisco on a Mac -- the Hub's screenshot is Segoe,
# and a system stack matches it without shipping a webfont the app would then
# have to load from a third party on every page view.
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)
DISPLAY_STACK = 'Georgia, "Times New Roman", serif'

# The switch's state, and -- because the widget is bound to the query string --
# also the name of the URL parameter that carries it: `?theme=light`.
_KEY = "theme"
_INJECTED = "_stl_theme_injected"

# Icon plus word, so the control reads at a glance and still says which is
# which. Material Symbols rather than emoji, for the reason BRAND_MARK gives.
_LABELS = {
    "dark": ":material/dark_mode: Dark",
    "light": ":material/light_mode: Light",
}


# --- Which appearance are we in? --------------------------------------------

def _detected() -> str:
    """
    The appearance to start a session in, most deliberate signal first: a
    `?theme=` in the URL (a reader's own choice, surviving a refresh), then
    what Streamlit rendered for the reader's system preference, then dark.

    The URL is read here as well as by the bound widget because `inject()` runs
    at the top of the script, before the switch exists -- on the first run of a
    session there is no widget state yet, and this is what stands in for it.

    `st.context` needs a live script run, so this is wrapped: importing the
    module or calling it from a test must not raise.
    """
    try:
        wanted = str(st.query_params.get(_KEY, "")).lower()
        if wanted in MODES:
            return wanted
    except Exception:
        pass

    try:
        # Documented as unreliable in the rerun *during* a theme change, which
        # is exactly why it is only ever read to seed the switch and never on
        # every rerun: once the switch exists, the switch is the truth.
        reported = st.context.theme.type
        if reported in MODES:
            return reported
    except Exception:
        pass

    return DEFAULT_MODE


def mode() -> str:
    """
    The active appearance: `"dark"` or `"light"`. Never anything else.

    Read from the switch's own state once it exists, and from `_detected()`
    before that -- so `inject()` at the top of the script and the switch drawn
    later in the rail always agree, including on the rerun that a click causes
    (widget state is updated before the script runs again).
    """
    chosen = st.session_state.get(_KEY)
    if chosen in MODES:
        return chosen
    return _detected()


def palette() -> dict:
    """The active palette. Handy for anything that needs a colour in Python."""
    return PALETTES[mode()]


def _remember():
    """
    Mirror the choice into the URL so a refresh keeps it.

    Runs as the switch's `on_change`, where the widget's state is already the
    new value. The URL is a convenience, not the source of truth, so a failure
    to write it is swallowed: the theme still applies for this session.
    """
    try:
        st.query_params[_KEY] = mode()
    except Exception:
        pass


def switch(label_visibility: str = "collapsed"):
    """
    The appearance switch: two chips, the active one lit, in the rail.

    `required=True` is what makes it a switch rather than a filter -- without
    it, clicking the lit chip clears the selection and the control has a third,
    meaningless state to interpret.

    The URL is written by hand rather than with `bind="query-params"`, which
    puts the *formatted* label in the parameter -- `?theme=:material/light_mode:
    Light` -- and that is both ugly and unreadable to `_detected()`, which is
    what paints the first frame of a reloaded page.
    """
    st.segmented_control(
        "Appearance",
        MODES,
        key=_KEY,
        default=_detected(),
        required=True,
        format_func=lambda m: _LABELS.get(m, m),
        on_change=_remember,
        help="Switch between the light and dark appearance.",
        label_visibility=label_visibility,
        width="stretch",
    )


# --- The stylesheet ----------------------------------------------------------

def _css(p: dict) -> str:
    return f"""
<style>
:root {{
  color-scheme: {p['scheme']};
  --stl-bg: {p['bg']};
  --stl-sidebar: {p['sidebar']};
  --stl-card: {p['card']};
  --stl-raised: {p['raised']};
  --stl-code: {p['code']};
  --stl-border: {p['border']};
  --stl-hairline: {p['hairline']};
  --stl-text: {p['text']};
  --stl-muted: {p['muted']};
  --stl-shadow: {p['shadow']};
  --stl-accent: {p['accent']};
  --stl-accent-soft: {p['accent_soft']};
  --stl-accent-line: {p['accent_line']};
  --stl-accent-ink: {p['accent_ink']};
  --stl-accent-hover: {p['accent_hover']};
  --stl-danger: {p['danger']};
  --stl-danger-soft: {p['danger_soft']};
  --stl-danger-line: {p['danger_line']};
  --stl-warn: {p['warn']};
  --stl-warn-soft: {p['warn_soft']};
  --stl-warn-line: {p['warn_line']};
  --stl-info: {p['info']};
  --stl-info-soft: {p['info_soft']};
  --stl-info-line: {p['info_line']};
}}

/* --- Page shell ---------------------------------------------------------
   The surfaces are `!important` because Streamlit paints them from its own
   theme, and that theme follows the system preference rather than the switch
   in the rail. Without this, flipping to light on a dark desktop would leave
   the page black under light panels. */

html, body, .stApp {{ font-family: {FONT_STACK}; }}
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
  background: var(--stl-bg) !important;
  color: var(--stl-text);
}}
/* The chat input sits in its own bottom bar, painted separately -- and the
   painted element is the anonymous div inside it, not the bar itself. */
[data-testid="stBottom"], [data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {{
  background: var(--stl-bg) !important;
}}

/* Streamlit draws its chevrons and control glyphs as Material *ligatures*:
   the element's text really is "keyboard_arrow_right", and only the icon font
   turns it into an arrow. Inheriting a text font here does not restyle the
   icon, it prints the word -- so icons are pinned back explicitly. */
[data-testid="stIconMaterial"], .material-icons, [class*="material-symbols"] {{
  font-family: "Material Symbols Rounded" !important;
}}

/* The default toolbar floats over the content. Left in place so the sidebar
   collapse control survives on a phone, but made invisible. */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 0.5rem; }}
/* The glyphs carry their own colour, so the icon is named as well as the
   button -- otherwise the collapse arrow stays near-white on a light page. */
[data-testid="stToolbar"] button, [data-testid="stToolbar"] [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] button,
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{
  color: var(--stl-muted) !important;
}}
#MainMenu, footer {{ visibility: hidden; }}

.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1100px; }}

h1, h2, h3, h4, h5, h6 {{ color: var(--stl-text) !important; letter-spacing: -0.01em; }}
hr, [data-testid="stDivider"] hr {{ border-color: var(--stl-hairline) !important; }}
a, a:visited {{ color: var(--stl-accent) !important; }}

/* Body copy and widget labels. Captions stay quiet. */
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] strong,
[data-testid="stWidgetLabel"] p,
label {{ color: var(--stl-text); }}
[data-testid="stCaption"], [data-testid="stCaption"] p,
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  color: var(--stl-muted) !important;
}}

/* Inline code, and the blocks `st.text`/`st.code`/`st.json` draw. */
[data-testid="stMarkdownContainer"] code,
[data-testid="stCaptionContainer"] code {{
  background: var(--stl-raised) !important;
  color: var(--stl-accent) !important;
  border: 1px solid var(--stl-border);
  border-radius: 5px;
  padding: 0.08em 0.34em;
}}
[data-testid="stCode"], [data-testid="stCode"] pre, [data-testid="stCode"] code,
[data-testid="stText"], [data-testid="stJson"],
[data-testid="stMarkdownPre"] pre {{
  background: var(--stl-code) !important;
  color: var(--stl-text) !important;
  border-radius: 8px;
}}
[data-testid="stText"], [data-testid="stCode"], [data-testid="stJson"] {{
  border: 1px solid var(--stl-border);
}}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{
  background: var(--stl-border); border-radius: 999px;
  border: 2px solid var(--stl-bg);
}}
::-webkit-scrollbar-thumb:hover {{ background: var(--stl-muted); }}

/* --- Sidebar ------------------------------------------------------------ */

[data-testid="stSidebar"] {{
  background: var(--stl-sidebar) !important;
  border-right: 1px solid var(--stl-border);
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
[data-testid="stSidebar"] hr {{ margin: 0.9rem 0; }}

/* Nav: one radio group, drawn as the Hub's rail. The dot is hidden by
   matching the wrapper that *contains* the input, so a miss leaves a visible
   dot rather than an invisible label. */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  display: flex; align-items: center;
  padding: 8px 11px; margin: 0;
  border-radius: 8px;
  border-left: 2px solid transparent;
  transition: background 0.12s ease, border-color 0.12s ease;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  background: var(--stl-raised);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: var(--stl-accent-soft);
  border-left-color: var(--stl-accent);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
  color: var(--stl-text); font-weight: 600;
}}
/* The dot itself: the box immediately before the label's text. Matched by its
   relationship to that text rather than by its emotion hash, and deliberately
   NOT by hiding the wrapper around the `input` -- that element is what keyboard
   focus lands on, so hiding it would cost the nav its tab order. */
[data-testid="stSidebar"] [role="radiogroup"] label
  div:has(> div[data-testid="stMarkdownContainer"]) > div:first-child {{
  display: none;
}}
[data-testid="stSidebar"] [role="radiogroup"] label p {{
  font-size: 0.92rem; color: var(--stl-muted);
}}

/* The appearance switch: two chips in a sunken pill, the active one lifted out
   of it. Streamlit's own segmented control is a row of separate buttons, so the
   pill is the group's background and the gap between chips is closed. */
.st-key-{_KEY} [data-testid="stButtonGroup"] {{
  background: var(--stl-raised);
  border: 1px solid var(--stl-border);
  border-radius: 9px;
  padding: 3px;
  gap: 3px;
  width: 100%;
}}
.st-key-{_KEY} [data-testid="stButtonGroup"] > div {{ flex: 1 1 0; }}
/* The chips are react-aria radios. Named by `data-variant` so the group's
   zero-sized help button is left out of the chip styling. */
.st-key-{_KEY} button[data-variant="segmented_control"] {{
  width: 100%;
  background: transparent !important;
  border: 1px solid transparent !important;
  border-radius: 7px !important;
  color: var(--stl-muted) !important;
  box-shadow: none !important;
  padding: 4px 6px !important;
  min-height: 0 !important;
  transition: background 0.12s ease, color 0.12s ease;
}}
.st-key-{_KEY} button p {{ font-size: 0.8rem !important; font-weight: 550; }}
.st-key-{_KEY} button [data-testid="stIconMaterial"] {{ font-size: 1rem !important; }}

/* The label's colour is stated on the text as well as on the chip. `inherit`
   is no use here: the `p` sits inside a markdown container that this stylesheet
   has already given a colour of its own, so it would inherit that instead. */
.st-key-{_KEY} button[data-variant="segmented_control"] p,
.st-key-{_KEY} button[data-variant="segmented_control"] [data-testid="stIconMaterial"] {{
  color: var(--stl-muted) !important;
}}
.st-key-{_KEY} button[data-variant="segmented_control"]:hover p,
.st-key-{_KEY} button[data-variant="segmented_control"]:hover [data-testid="stIconMaterial"] {{
  color: var(--stl-text) !important;
}}
/* The lit chip: matched on the state the control itself reports, so a screen
   reader and the eye are told the same thing. */
.st-key-{_KEY} button[aria-checked="true"] {{
  background: var(--stl-card) !important;
  border-color: var(--stl-accent-line) !important;
  box-shadow: var(--stl-shadow) !important;
}}
.st-key-{_KEY} button[aria-checked="true"] p,
.st-key-{_KEY} button[aria-checked="true"] [data-testid="stIconMaterial"] {{
  color: var(--stl-accent) !important;
}}

/* --- Panels ------------------------------------------------------------- */

[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border-radius: 10px;
}}
[data-testid="stExpander"] details {{
  background: var(--stl-card) !important;
  border: 1px solid var(--stl-border) !important;
  border-radius: 10px;
  box-shadow: var(--stl-shadow);
}}
[data-testid="stExpander"] summary {{
  background: var(--stl-card) !important;
  color: var(--stl-text) !important;
}}
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] summary:hover p {{ color: var(--stl-accent) !important; }}

[data-testid="stMetric"] {{
  background: var(--stl-card) !important;
  border: 1px solid var(--stl-border);
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: var(--stl-shadow);
}}
[data-testid="stMetricValue"] {{ color: var(--stl-accent) !important; font-weight: 600; }}
[data-testid="stMetricLabel"] p {{ color: var(--stl-muted) !important; }}

/* Alerts. Streamlit tints these from its own theme, so the tint is re-stated
   here in the switch's colours. The *kind* is only visible in the DOM on the
   inner content node, hence `:has()` -- and a browser without it simply keeps
   Streamlit's tint, which config.toml already matched to these palettes. */
[data-testid="stAlertContainer"] {{
  background: var(--stl-card) !important;
  border: 1px solid var(--stl-border) !important;
  border-left: 3px solid var(--stl-muted) !important;
  border-radius: 10px !important;
  color: var(--stl-text) !important;
}}
[data-testid="stAlertContainer"] p,
[data-testid="stAlertContainer"] li,
[data-testid="stAlertContainer"] code {{ color: var(--stl-text) !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{
  background: var(--stl-accent-soft) !important;
  border-color: var(--stl-accent-line) !important;
  border-left-color: var(--stl-accent) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
  background: var(--stl-warn-soft) !important;
  border-color: var(--stl-warn-line) !important;
  border-left-color: var(--stl-warn) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
  background: var(--stl-danger-soft) !important;
  border-color: var(--stl-danger-line) !important;
  border-left-color: var(--stl-danger) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
  background: var(--stl-info-soft) !important;
  border-color: var(--stl-info-line) !important;
  border-left-color: var(--stl-info) !important;
}}
[data-testid="stAlertContentSuccess"] [data-testid="stIconMaterial"] {{ color: var(--stl-accent) !important; }}
[data-testid="stAlertContentWarning"] [data-testid="stIconMaterial"] {{ color: var(--stl-warn) !important; }}
[data-testid="stAlertContentError"] [data-testid="stIconMaterial"] {{ color: var(--stl-danger) !important; }}
[data-testid="stAlertContentInfo"] [data-testid="stIconMaterial"] {{ color: var(--stl-info) !important; }}

[data-testid="stChatMessage"] {{
  background: var(--stl-card) !important;
  border: 1px solid var(--stl-border);
  border-radius: 10px;
  box-shadow: var(--stl-shadow);
}}
/* A `:material/...:` avatar is an "avatar custom", which Streamlit paints a
   fixed near-black regardless of theme -- so this is matched by prefix and
   restated in both appearances, not just in light. */
[data-testid^="stChatMessageAvatar"] {{
  background-color: var(--stl-accent-soft) !important;
  color: var(--stl-accent) !important;
  border: 1px solid var(--stl-accent-line) !important;
}}
/* The glyph carries its own colour and does not inherit the chip's. */
[data-testid^="stChatMessageAvatar"] [data-testid="stIconMaterial"],
[data-testid^="stChatMessageAvatar"] svg {{
  color: var(--stl-accent) !important;
  fill: var(--stl-accent) !important;
}}
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {{
  background: var(--stl-card) !important;
  border-color: var(--stl-border) !important;
  border-radius: 10px;
}}
[data-testid="stChatInput"] {{ border: 1px solid var(--stl-border); }}
[data-testid="stChatInputTextArea"] {{
  background: transparent !important;
  color: var(--stl-text) !important;
}}
[data-testid="stChatInputTextArea"]::placeholder {{ color: var(--stl-muted) !important; }}
[data-testid="stChatInputSubmitButton"] {{
  background: var(--stl-accent) !important;
  color: var(--stl-accent-ink) !important;
}}
[data-testid="stChatInputSubmitButton"] svg,
[data-testid="stChatInputSubmitButton"] [data-testid="stIconMaterial"] {{
  color: var(--stl-accent-ink) !important;
}}
[data-testid="stChatInputInstructions"] {{ color: var(--stl-muted) !important; }}

/* --- Controls ----------------------------------------------------------- */

/* The uploader's own browse button is not inside a `.stButton`, so it needs
   naming separately or it keeps Streamlit's fill -- black text on black in a
   light page. */
.stButton > button, .stDownloadButton > button,
[data-testid="stFileUploaderDropzone"] button {{
  background: var(--stl-card) !important;
  color: var(--stl-text) !important;
  border: 1px solid var(--stl-border) !important;
  border-radius: 8px;
  font-weight: 500;
  box-shadow: var(--stl-shadow);
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover,
[data-testid="stFileUploaderDropzone"] button:hover {{
  background: var(--stl-accent-soft) !important;
  border-color: var(--stl-accent) !important;
  color: var(--stl-accent) !important;
}}
.stButton > button[kind="primary"] {{
  background: var(--stl-accent) !important;
  border-color: var(--stl-accent) !important;
  color: var(--stl-accent-ink) !important;
  font-weight: 600;
}}
.stButton > button[kind="primary"]:hover {{
  background: var(--stl-accent-hover) !important;
  border-color: var(--stl-accent-hover) !important;
  color: var(--stl-accent-ink) !important;
}}

/* Text fields. The visible box is the *root element*, not the `input` inside
   it -- style only the inner one and its dark 1px frame stays behind. */
[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stNumberInputContainer"] {{
  background: var(--stl-raised) !important;
  border-color: var(--stl-border) !important;
}}
.stTextInput input, .stTextArea textarea, .stNumberInput input {{
  background: transparent !important;
  border-color: var(--stl-border) !important;
  color: var(--stl-text) !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {{
  color: var(--stl-muted) !important;
}}

/* Selectbox. Streamlit 1.60 builds this on react-aria, so the closed control
   is a `role="group"` and the open menu a portalled `role="listbox"` -- there
   is no `data-baseweb="select"` here any more. */
[data-testid="stSelectbox"] div[role="group"],
[data-testid="stMultiSelect"] div[role="group"] {{
  background: var(--stl-raised) !important;
  border-color: var(--stl-border) !important;
  color: var(--stl-text) !important;
}}
[data-testid="stSelectbox"] input, [data-testid="stMultiSelect"] input {{
  background: transparent !important; color: var(--stl-text) !important;
}}
[data-testid="stSelectbox"] input::placeholder {{ color: var(--stl-muted) !important; }}
[data-testid="stSelectbox"] button svg, [data-testid="stMultiSelect"] button svg {{
  color: var(--stl-muted) !important; fill: var(--stl-muted) !important;
}}
/* The open menu is portalled to the end of `body`, outside `.stApp`, so it is
   matched globally rather than inside the app container. */
[data-testid="stSelectboxVirtualDropdown"],
[data-testid="stMultiSelectVirtualDropdown"],
[role="listbox"] {{
  background: var(--stl-card) !important;
  border-color: var(--stl-border) !important;
}}
[role="option"] {{ background: transparent !important; color: var(--stl-text) !important; }}
[role="option"]:hover, [role="option"][data-focused], [role="option"][aria-selected="true"] {{
  background: var(--stl-accent-soft) !important;
  color: var(--stl-accent) !important;
}}

/* Checkbox and toggle share one shape: a hidden `input` in a `span`, then the
   visible box -- a tick box, or a switch track holding a thumb. Matching that
   box as `span + div` keeps the rule off the icons and tooltip in the label
   beside it, which a looser `span`/`div` match sweeps up and paints green. */
[data-testid="stCheckbox"] > label > span + div {{
  background-color: var(--stl-raised) !important;
  border-color: var(--stl-border) !important;
}}
[data-testid="stCheckbox"] > label:has(input:checked) > span + div {{
  background-color: var(--stl-accent) !important;
  border-color: var(--stl-accent) !important;
}}
[data-testid="stCheckbox"] > label > span + div svg {{ fill: var(--stl-accent-ink) !important; }}
[data-testid="stCheckbox"] > label > span + div > div {{ background-color: #FFFFFF !important; }}
[data-testid="stCheckbox"] label p {{ color: var(--stl-text); }}

/* The track is the outer element and the fill its child, so painting the
   outer one green would fill the whole bar. */
[data-testid="stProgressBarTrack"] {{ background: var(--stl-raised) !important; }}
[data-testid="stProgressBarTrack"] > div {{ background: var(--stl-accent) !important; }}

/* The little "?" beside a widget label, and the bubble it opens. The bubble is
   portalled out of `.stApp`, so it is matched globally. */
[data-testid="stTooltipIcon"] svg {{ color: var(--stl-muted) !important; }}
[data-testid="stTooltipHoverTarget"]:hover svg {{ color: var(--stl-accent) !important; }}
[data-testid="stTooltipContent"] {{
  background: var(--stl-card) !important;
  color: var(--stl-text) !important;
  border: 1px solid var(--stl-border) !important;
  border-radius: 8px;
}}
[data-testid="stTooltipContent"] p, [data-testid="stTooltipContent"] code {{
  color: var(--stl-text) !important;
}}
[data-testid="stSpinner"] p, [data-testid="stSpinner"] div {{ color: var(--stl-muted); }}

[data-testid="stFileUploaderDropzone"] {{
  background: var(--stl-card) !important;
  border: 1px dashed var(--stl-border) !important;
  border-radius: 10px;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--stl-accent) !important; }}
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small {{ color: var(--stl-muted) !important; }}
[data-testid="stFileUploaderFile"] {{ color: var(--stl-text) !important; }}

*:focus-visible {{ outline: 2px solid var(--stl-accent) !important; outline-offset: 1px; }}

/* --- Pieces drawn by this module --------------------------------------- */

.stl-brand {{
  display: flex; align-items: center; gap: 10px;
  padding: 4px 2px 14px 2px;
  border-bottom: 1px solid var(--stl-border);
  margin-bottom: 14px;
}}
.stl-brand-mark {{
  width: 30px; height: 30px; flex: none;
  display: grid; place-items: center;
  background: var(--stl-accent-soft);
  border: 1px solid var(--stl-accent-line);
  border-radius: 8px;
  color: var(--stl-accent);
}}
.stl-brand-mark svg {{ display: block; }}
.stl-brand-name {{
  font-size: 0.98rem; font-weight: 650; color: var(--stl-text);
  line-height: 1.15;
}}
.stl-brand-sub {{ font-size: 0.7rem; color: var(--stl-muted); letter-spacing: 0.04em; }}

.stl-crumb {{
  font-size: 0.8rem; color: var(--stl-muted); margin-bottom: 2px;
}}
.stl-crumb b {{ color: var(--stl-text); font-weight: 500; }}
.stl-title {{
  font-family: {DISPLAY_STACK}; font-style: italic;
  font-size: 1.72rem; color: var(--stl-text);
  margin: 0 0 2px 0; line-height: 1.2;
}}
.stl-sub {{ font-size: 0.86rem; color: var(--stl-muted); margin-bottom: 4px; }}

.stl-pill {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 10px; border-radius: 999px;
  font-size: 0.76rem; font-weight: 600; line-height: 1.5;
  border: 1px solid transparent;
}}
.stl-pill.ok {{
  color: var(--stl-accent); background: var(--stl-accent-soft);
  border-color: var(--stl-accent-line);
}}
.stl-pill.bad {{
  color: var(--stl-danger); background: var(--stl-danger-soft);
  border-color: var(--stl-danger-line);
}}
.stl-pill.warn {{
  color: var(--stl-warn); background: var(--stl-warn-soft);
  border-color: var(--stl-warn-line);
}}
.stl-pill.mute {{
  color: var(--stl-muted); background: var(--stl-raised);
  border-color: var(--stl-border);
}}

.stl-account {{
  display: flex; align-items: center; gap: 10px;
  padding: 10px; border-radius: 10px;
  background: var(--stl-card); border: 1px solid var(--stl-border);
  box-shadow: var(--stl-shadow);
}}
.stl-avatar {{
  width: 30px; height: 30px; flex: none;
  display: grid; place-items: center; border-radius: 8px;
  background: var(--stl-accent-soft); color: var(--stl-accent);
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.02em;
}}
.stl-account-name {{
  font-size: 0.84rem; font-weight: 600; color: var(--stl-text); line-height: 1.2;
}}
.stl-account-sub {{
  font-size: 0.72rem; color: var(--stl-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}

.stl-note {{
  padding: 14px 16px; border-radius: 10px;
  background: var(--stl-card); border: 1px solid var(--stl-border);
  border-left: 3px solid var(--stl-accent);
  box-shadow: var(--stl-shadow);
  font-size: 0.9rem; color: var(--stl-muted);
}}
.stl-note.bad {{ border-left-color: var(--stl-danger); }}
.stl-note b {{ color: var(--stl-text); }}

.stl-section {{
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.09em;
  color: var(--stl-muted); text-transform: uppercase;
  margin: 2px 0 6px 2px;
}}

/* --- Phones ------------------------------------------------------------- */
/* Streamlit collapses the rail behind a hamburger on a narrow screen and
   leaves everything else at desktop proportions. The rest is up to us. */
@media (max-width: 640px) {{

  /* Columns keep their row on a phone and just get narrower, so the three
     pricing tiers and the five-star breakdown arrive as unreadable slivers.
     Stack them: a tall column beats five columns nothing fits in. */
  [data-testid="stHorizontalBlock"] {{
    flex-direction: column;
    gap: 0.75rem;
  }}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0 !important;
  }}

  /* Desktop gutters cost about a fifth of the usable width here. */
  .block-container {{
    padding-top: 1.2rem;
    padding-left: 1rem;
    padding-right: 1rem;
    padding-bottom: 3rem;
  }}

  /* iOS Safari zooms the whole page in whenever a focused field is under 16px,
     and it does not zoom back out afterwards -- so a seller who taps one form
     field spends the rest of the session scrolling sideways. 16px is the
     threshold, not a preference. */
  input, textarea, select,
  [data-testid="stChatInput"] textarea,
  [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
  [data-baseweb="select"] div {{
    font-size: 16px !important;
  }}

  /* Anything with a fixed intrinsic width scrolls inside itself rather than
     pushing the whole page sideways. */
  [data-testid="stMarkdownContainer"] pre,
  [data-testid="stMarkdownContainer"] table,
  [data-testid="stDataFrame"] {{
    max-width: 100%;
    overflow-x: auto;
  }}
  [data-testid="stMarkdownContainer"] {{ overflow-wrap: anywhere; }}

  /* Full-width tap targets. A stacked button that only spans half the column
     is a small target next to a lot of dead space. */
  .stButton > button, .stDownloadButton > button {{ width: 100%; }}

  /* The rail is an overlay here, so it can afford to be wide enough to read. */
  [data-testid="stSidebar"] {{ min-width: 17rem !important; }}
}}
</style>
"""


def inject():
    """Apply the stylesheet for the active mode. Safe on every rerun."""
    st.markdown(_css(palette()), unsafe_allow_html=True)
    st.session_state[_INJECTED] = True


# --- Small pieces -----------------------------------------------------------

# A drawn mark rather than an emoji. An emoji is a different picture in every
# font -- the same character is a pink blob on one machine and a grey outline on
# another -- and it cannot take the accent colour. This is four linked nodes,
# stroked in `currentColor`, so it is the same shape everywhere and turns green
# because its container is green -- in either theme, at either green.
BRAND_MARK = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="6.2" cy="7" r="2.1"/>'
    '<circle cx="17.4" cy="5.6" r="1.9"/>'
    '<circle cx="16.2" cy="17.2" r="2.3"/>'
    '<circle cx="7" cy="16.1" r="1.7"/>'
    '<path d="M8.2 8.5 L14.5 15.6"/>'
    '<path d="M8.3 6.4 L15.5 5.8"/>'
    '<path d="M6.5 9.1 L6.9 14.4"/>'
    '<path d="M8.7 15.8 L13.9 17"/>'
    '</svg>'
)


def brand(name: str = "Fiverr Brain", sub: str = "SILVERTHREAD LABS",
          mark: str = BRAND_MARK):
    """The rail's masthead, matching the Hub's logo block."""
    st.markdown(
        f'<div class="stl-brand">'
        f'  <div class="stl-brand-mark">{mark}</div>'
        f'  <div>'
        f'    <div class="stl-brand-name">{name}</div>'
        f'    <div class="stl-brand-sub">{sub}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def section(label: str):
    st.markdown(f'<div class="stl-section">{label}</div>', unsafe_allow_html=True)


def page_header(section_name: str, page: str, subtitle: str = "",
                pills: str = ""):
    """Breadcrumb, title, and an optional right-hand status pill row."""
    crumb = (f'<div class="stl-crumb">{section_name} &nbsp;›&nbsp; '
             f'<b>{page}</b></div>')
    title = f'<div class="stl-title">{page}</div>'
    sub = f'<div class="stl-sub">{subtitle}</div>' if subtitle else ""

    if pills:
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.markdown(crumb + title + sub, unsafe_allow_html=True)
        with right:
            st.markdown(
                f'<div style="text-align:right">{pills}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(crumb + title + sub, unsafe_allow_html=True)

    st.markdown(
        '<hr style="margin:14px 0 18px 0;border:none;'
        'border-top:1px solid var(--stl-border)">',
        unsafe_allow_html=True,
    )


def pill(text: str, kind: str = "mute") -> str:
    """A status chip. `kind` is one of: ok, bad, warn, mute."""
    return f'<span class="stl-pill {kind}">{text}</span>'


def note(html: str, kind: str = "ok"):
    css_class = "stl-note bad" if kind == "bad" else "stl-note"
    st.markdown(f'<div class="{css_class}">{html}</div>', unsafe_allow_html=True)


def account_card(name: str, sub: str):
    """The rail's footer card -- who the answers are about."""
    initials = "".join(w[0] for w in str(name).split()[:2]).upper() or "FB"
    st.markdown(
        f'<div class="stl-account">'
        f'  <div class="stl-avatar">{initials}</div>'
        f'  <div style="min-width:0">'
        f'    <div class="stl-account-name">{name}</div>'
        f'    <div class="stl-account-sub">{sub}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )
