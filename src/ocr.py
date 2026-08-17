"""
Screenshot import: a Fiverr gig or profile screenshot in, structured profile
data out.

The extraction is done by Claude's vision, not by a local OCR engine.
Tesseract would give back a bag of words in reading order; what this needs is
the *structure* -- which number is the Standard price and which is the delivery
time -- and that is a job for a model that can read a layout.

Three things make the output trustworthy enough to show a user:

  1. The response is bound to `SellerProfile`'s own JSON schema, so the reply is
     shaped correctly by construction rather than by hopeful parsing.
  2. The prompt requires `null` for anything not visible and forbids inference.
     A screenshot of one gig genuinely does not show the seller's country.
  3. Nothing is ever saved from here directly. The caller gets the parsed model
     plus a confidence report, and the user edits and confirms before it lands.

Uploads are validated before any of that: images only, 10 MB cap, and the file
is re-encoded through Pillow, which drops EXIF -- a phone screenshot can carry
GPS coordinates, and nothing downstream needs them.

The model is also the gate: it must first declare whether the image is from
Fiverr at all. A non-Fiverr image (a random photo, another site, another
freelance platform) raises `NotFiverrError` and nothing is extracted.
"""
import base64
import io
import json
from typing import List, Optional, Tuple

import anthropic

from . import config
from .schema import ScreenshotReading, SellerProfile, ocr_json_schema

EXTRACTION_PROMPT = """You are reading a screenshot and extracting what it shows
into structured data — but ONLY if the screenshot is from Fiverr.

FIRST, decide: is this image from Fiverr? Fiverr screenshots include a
fiverr.com page or the Fiverr app — a seller profile, gig page, order page,
inbox, dashboard, earnings, analytics or reviews. Look for Fiverr's layout,
branding, URLs or wording.

- If it IS from Fiverr: set is_fiverr_screenshot to true, describe the page in
  one sentence in image_shows, and extract everything visible into profile.
- If it is NOT from Fiverr (a random photo, a document, a chat, another
  website, another freelance platform like Upwork or Freelancer): set
  is_fiverr_screenshot to false, say what the image actually shows in
  image_shows, and leave every profile field null with empty lists. Extract
  NOTHING from a non-Fiverr image.

Absolute rules for the extraction:
- Return ONLY what is visibly present in the image.
- Use null for every field you cannot read in the image. Empty lists for lists.
- NEVER infer, guess, complete or invent a value. If a price is cut off, it is
  null. If the country is not shown, it is null. A plausible-looking guess is
  worse than a null, because the user cannot tell the two apart.
- Do not carry knowledge about Fiverr in general into the answer. A field is
  filled in only because you can see it in this image.
- Copy text as written, including the seller's own wording and spelling.
- For prices, give the number only, without a currency symbol.
- Match each pricing column to its tier: basic, standard, premium.
- Leave seller_id and gig_id null; the system assigns them.

Return the data now."""


class OCRError(RuntimeError):
    """Raised when a screenshot cannot be turned into structured data."""


class NotFiverrError(OCRError):
    """Raised when the uploaded image is not a Fiverr screenshot at all."""


# --- Upload validation ------------------------------------------------------

def validate_image(data: bytes, filename: str = "") -> None:
    """Reject anything that is not a reasonable image. Raises OCRError."""
    if not data:
        raise OCRError("That file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise OCRError(
            f"That image is {len(data) / 1_048_576:.1f} MB. The limit is "
            f"{config.MAX_UPLOAD_BYTES // 1_048_576} MB — crop it or save it "
            f"at a lower quality."
        )

    from PIL import Image, UnidentifiedImageError

    try:
        # verify() checks the header without decoding the whole file, so a
        # renamed .exe is caught before anything expensive happens.
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
            fmt = (img.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError):
        raise OCRError(
            f"`{filename or 'That file'}` is not an image the app can read. "
            f"Upload a PNG, JPEG, WEBP, GIF or BMP screenshot."
        )

    if fmt not in config.ALLOWED_IMAGE_FORMATS:
        raise OCRError(
            f"`{fmt}` images are not accepted. Use one of: "
            f"{', '.join(sorted(config.ALLOWED_IMAGE_FORMATS))}."
        )


def strip_exif(data: bytes) -> bytes:
    """Re-encode to PNG through a fresh image object.

    Pillow copies metadata only when asked to, so building a new image from the
    pixel data and saving that leaves EXIF, GPS tags and colour profiles behind
    -- which matters, because a screenshot taken on a phone can carry the
    location it was taken at.
    """
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        rgb = img.convert("RGB")
        clean = Image.new("RGB", rgb.size)
        clean.paste(rgb)
        out = io.BytesIO()
        clean.save(out, format="PNG")
    return out.getvalue()


def prepare_upload(data: bytes, filename: str = "") -> bytes:
    """Validate, then return EXIF-free bytes ready to send."""
    validate_image(data, filename)
    return strip_exif(data)


def to_base64(png_bytes: bytes) -> str:
    """The image as Claude wants it: bare base64, no data-URL prefix."""
    return base64.b64encode(png_bytes).decode("ascii")


# --- Confidence -------------------------------------------------------------

def _count_fields(model, path="") -> Tuple[int, int, List[str]]:
    """(populated, total, names_of_populated) over a pydantic model tree."""
    from pydantic import BaseModel

    populated, total, names = 0, 0, []
    for name, value in model:
        if name in ("seller_id", "source_type"):
            continue  # assigned by the system, not read from the image
        label = f"{path}{name}"

        if isinstance(value, BaseModel):
            p, t, n = _count_fields(value, path=f"{label}.")
            populated, total, names = populated + p, total + t, names + n
            continue

        if isinstance(value, list):
            total += 1
            if value:
                populated += 1
                names.append(label)
            for i, item in enumerate(value):
                if isinstance(item, BaseModel):
                    p, t, n = _count_fields(item, path=f"{label}[{i}].")
                    populated, total, names = populated + p, total + t, names + n
            continue

        total += 1
        if value is not None and str(value).strip():
            populated += 1
            names.append(label)
    return populated, total, names


def confidence_report(profile: SellerProfile) -> dict:
    """What the extraction actually found, so the UI can be honest about it."""
    populated, total, names = _count_fields(profile)
    ratio = (populated / total) if total else 0.0

    found = {
        "basic information": any(n.startswith("basic.") for n in names),
        "bio": any(n.startswith("about.") for n in names),
        "skills": any(n.startswith("skills.") for n in names),
        "gigs": bool(profile.gigs),
        "portfolio": bool(profile.portfolio),
        "reviews": bool(profile.reviews) or any(
            v is not None for v in profile.review_summary.model_dump().values()
        ),
    }

    return {
        "populated": populated,
        "total": total,
        "ratio": ratio,
        "low_confidence": ratio < config.OCR_MIN_CONFIDENCE,
        "sections_found": [k for k, v in found.items() if v],
        "sections_missing": [k for k, v in found.items() if not v],
        "fields": names,
    }


# --- Extraction -------------------------------------------------------------

def extract(image_bytes: bytes, filename: str = "", client=None
            ) -> Tuple[SellerProfile, dict]:
    """Screenshot -> (profile, confidence report).

    `client` is injectable so tests can exercise the whole path -- validation,
    EXIF stripping, schema binding, parsing, confidence -- without a paid call.
    """
    png = prepare_upload(image_bytes, filename)

    if client is None:
        if not config.ANTHROPIC_API_KEY:
            raise OCRError(
                "ANTHROPIC_API_KEY is not set, so the screenshot cannot be "
                "read. Add it to your .env file or Streamlit Secrets."
            )
        client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY, timeout=120.0
        )

    try:
        response = client.messages.create(
            model=config.VISION_MODEL,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            # The schema is the contract: the reply is shaped by construction,
            # so nothing downstream has to parse hopefully.
            output_config={
                "effort": config.VISION_EFFORT,
                "format": {"type": "json_schema", "schema": ocr_json_schema()},
            },
            messages=[{
                "role": "user",
                # Image first, then the instruction -- the model reads the
                # picture better when it is not answering a question it has
                # already been asked.
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/png",
                                "data": to_base64(png)}},
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        raise OCRError(
            "Your Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
        )
    except anthropic.RateLimitError:
        raise OCRError(
            "Anthropic rate limit or quota hit. Wait a moment and retry, or "
            "check your usage at console.anthropic.com."
        )
    except anthropic.APITimeoutError:
        raise OCRError(
            "Reading the screenshot timed out. Try a smaller or simpler image."
        )
    except anthropic.APIConnectionError:
        raise OCRError("Could not reach Anthropic. Check your connection and retry.")
    except anthropic.APIError as e:
        raise OCRError(f"Anthropic returned an error while reading the image: {e}")

    if response.stop_reason == "refusal":
        raise OCRError(
            "Claude declined to read that image, so nothing was extracted. "
            "Upload a different Fiverr screenshot, or enter the profile "
            "manually."
        )

    content = "".join(
        block.text for block in response.content if block.type == "text"
    )
    if not content.strip():
        raise OCRError(
            "The model returned nothing for that screenshot. Try a clearer or "
            "less cropped image."
        )

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        raise OCRError(
            "The model's reply was not valid JSON, so nothing was imported. "
            "Retry, or enter the profile manually."
        )

    try:
        reading = ScreenshotReading.model_validate(payload)
    except Exception as e:
        raise OCRError(
            f"The extracted data did not match the profile schema, so nothing "
            f"was imported: {e}"
        )

    if not reading.is_fiverr_screenshot:
        shows = (reading.image_shows or "").strip()
        detail = f"It appears to show: **{shows}**\n\n" if shows else ""
        raise NotFiverrError(
            "I can't read this screenshot — it is not a Fiverr image, so "
            "nothing was extracted.\n\n"
            f"{detail}"
            "This tool only reads screenshots from Fiverr: a seller profile, "
            "a gig page, orders, reviews or anything else from fiverr.com. "
            "Please upload a Fiverr screenshot instead."
        )

    profile = reading.profile
    profile.source_type = "ocr"
    report = confidence_report(profile)
    report["image_shows"] = (reading.image_shows or "").strip()
    return profile, report


def merge_into(base: Optional[SellerProfile], extracted: SellerProfile
               ) -> SellerProfile:
    """Overlay an extraction onto an existing profile without erasing anything.

    A screenshot of one gig should add that gig, not replace a full profile
    with six nulls and a price. Only fields the extraction actually found are
    written; lists are extended, and a gig whose title already exists is
    replaced rather than duplicated.
    """
    if base is None:
        return extracted

    merged = base.model_copy(deep=True)

    for section in ("basic", "about", "skills"):
        target, incoming = getattr(merged, section), getattr(extracted, section)
        for name, value in incoming:
            if isinstance(value, list):
                if value:
                    existing = list(getattr(target, name))
                    existing += [v for v in value if v not in existing]
                    setattr(target, name, existing)
            elif value is not None and str(value).strip():
                setattr(target, name, value)

    by_title = {(g.title or "").strip().lower(): i
                for i, g in enumerate(merged.gigs) if g.title}
    for gig in extracted.gigs:
        key = (gig.title or "").strip().lower()
        if key and key in by_title:
            merged.gigs[by_title[key]] = gig
        else:
            merged.gigs.append(gig)

    merged.portfolio += [p for p in extracted.portfolio
                         if p.model_dump() not in
                         [x.model_dump() for x in merged.portfolio]]
    merged.reviews += [r for r in extracted.reviews
                       if r.model_dump() not in
                       [x.model_dump() for x in merged.reviews]]

    for name, value in extracted.review_summary:
        if value is not None:
            setattr(merged.review_summary, name, value)

    # The result is part manual, part OCR. Calling it "ocr" is the honest
    # label: it means at least some of this was machine-read.
    merged.source_type = "ocr"
    return merged
