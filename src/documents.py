"""
Profile -> retrievable documents.

A stored profile is a graph of rows. Retrieval needs prose. This module is the
join between them: it turns one `SellerProfile` into a small set of documents,
each covering one logical unit the brief names -- the bio, each gig, each
portfolio item, and a single reviews digest.

Why not one document per row: a buyer-facing question ("what does the standard
package include?") is answered by a gig *as a whole*, not by a packages row. A
gig split across five documents retrieves one fifth of an answer. Grouping at
the logical unit keeps each chunk self-contained, which is also what makes the
citations shown in the UI readable.

Basic information and skills ride along in the bio document rather than getting
one of their own. They are short, they are about the same subject -- who this
seller is -- and questions like "what languages do you speak" have to land
somewhere retrievable.

Every document carries `sellerId`, `sectionType`, `gigId` and `sourceType`, the
four metadata keys the brief specifies. `layer` and `source` are carried too:
the existing modes filter on `layer`, and citations read better with a name.
"""
from typing import List, Optional

from .schema import SellerProfile, format_number

SECTION_TYPES = ("bio", "gig", "portfolio", "reviews")

# Chroma rejects a None in metadata, and a missing key cannot be matched by a
# `where` filter, so every document gets every key with a real value.
NO_GIG = "N/A"


def _lines(*parts) -> str:
    return "\n".join(p for p in parts if p and str(p).strip())


def _labelled(label: str, value) -> Optional[str]:
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v).strip() for v in value if str(v).strip())
    value = str(value or "").strip()
    return f"{label}: {value}" if value else None


def _doc(seller_id, section_type, doc_id, title, text, source_type,
         gig_id=NO_GIG) -> dict:
    return {
        "id": doc_id,
        "text": text,
        "metadata": {
            "sellerId": seller_id,
            "sectionType": section_type,
            "gigId": gig_id,
            "sourceType": source_type,
            # Kept for the existing layer filters and for citation display.
            "layer": "profile_gigs",
            "source": title,
            "gig_name": title if section_type == "gig" else "N/A",
        },
    }


def bio_document(profile: SellerProfile) -> Optional[dict]:
    seller_id = profile.resolved_seller_id()
    b, a, s = profile.basic, profile.about, profile.skills

    name = (b.name or b.username or "This seller").strip()
    body = _lines(
        f"# Seller profile: {name}",
        _labelled("Fiverr username", b.username),
        _labelled("Headline", b.headline),
        _labelled("Fiverr level", b.level),
        _labelled("Country", b.country),
        _labelled("Languages", b.languages),
        _labelled("Member since", b.member_since),
        _labelled("Average response time", b.avg_response_time),
        "",
        f"## About\n{a.bio.strip()}" if a.bio and a.bio.strip() else None,
        f"## Working style\n{a.working_style.strip()}"
        if a.working_style and a.working_style.strip() else None,
        "## Skills\n" + "\n".join(f"- {x}" for x in s.skills)
        if s.skills else None,
        "## Education\n" + "\n".join(f"- {x}" for x in s.education)
        if s.education else None,
        "## Certifications\n" + "\n".join(f"- {x}" for x in s.certifications)
        if s.certifications else None,
        "## Skill tests\n" + "\n".join(f"- {x}" for x in s.tests)
        if s.tests else None,
    )

    # A document holding nothing but a heading is noise in the index -- it
    # matches weakly against everything and answers nothing.
    if not _lines(
        a.bio, b.headline, b.country, b.member_since, b.avg_response_time,
        ", ".join(s.skills), ", ".join(b.languages),
    ):
        return None

    return _doc(seller_id, "bio", f"{seller_id}__bio",
                f"{seller_id}_profile.md", body, profile.source_type)


def gig_document(profile: SellerProfile, gig, index: int) -> Optional[dict]:
    seller_id = profile.resolved_seller_id()
    from .schema import derive_gig_id

    gig_id = gig.gig_id or derive_gig_id(seller_id, gig.title, index)
    title = (gig.title or f"Gig {index + 1}").strip()

    package_blocks = []
    for pkg in gig.packages:
        tier = (pkg.tier or "package").capitalize()
        head = _labelled(f"### {tier}", pkg.name) or f"### {tier}"
        if pkg.price is None:
            price = None
        elif pkg.currency and pkg.currency.upper() not in ("USD", "$"):
            price = f"{format_number(pkg.price)} {pkg.currency}"
        else:
            price = f"${format_number(pkg.price)}"
        detail = ", ".join(x for x in [
            price,
            f"{pkg.delivery_days} day delivery" if pkg.delivery_days is not None else None,
            f"{pkg.revisions} revisions" if pkg.revisions else None,
        ] if x)
        features = "\n".join(f"- {f}" for f in pkg.features)
        package_blocks.append(_lines(head, detail, features))

    faq_block = "\n\n".join(
        f"**Q: {f.question.strip()}**\nA: {(f.answer or '').strip()}"
        for f in gig.faqs if f.question and f.question.strip()
    )

    body = _lines(
        f"# Gig: {title}",
        _labelled("Category", gig.category),
        f"\n## Description\n{gig.description.strip()}"
        if gig.description and gig.description.strip() else None,
        "\n## Pricing packages\n" + "\n\n".join(package_blocks)
        if package_blocks else None,
        "\n## Gig extras\n" + "\n".join(f"- {e}" for e in gig.extras)
        if gig.extras else None,
        f"\n## FAQs\n{faq_block}" if faq_block else None,
    )

    if not _lines(gig.title, gig.description) and not package_blocks:
        return None

    return _doc(seller_id, "gig", gig_id, f"gig_{gig_id}.md", body,
                profile.source_type, gig_id=gig_id)


def portfolio_document(profile: SellerProfile, item, index: int) -> Optional[dict]:
    seller_id = profile.resolved_seller_id()
    title = (item.title or f"Portfolio item {index + 1}").strip()

    body = _lines(
        f"# Portfolio: {title}",
        item.description.strip() if item.description else None,
        _labelled("Link", item.link),
        _labelled("Image", item.image_url),
    )

    if not _lines(item.title, item.description, item.link):
        return None

    return _doc(seller_id, "portfolio", f"{seller_id}__portfolio_{index}",
                f"portfolio_{index + 1}.md", body, profile.source_type)


def reviews_document(profile: SellerProfile) -> Optional[dict]:
    """One digest, not one document per review.

    Individual reviews are a sentence each; indexed separately they would flood
    the top-5 with near-identical praise and crowd out the gig that actually
    answers the question.
    """
    seller_id = profile.resolved_seller_id()
    s = profile.review_summary

    breakdown = "\n".join(
        f"- {stars} star: {count} review(s)"
        for stars, count in s.breakdown().items() if count
    )
    review_lines = []
    for r in profile.reviews:
        if not (r.text and r.text.strip()):
            continue
        meta = ", ".join(x for x in [
            f"{format_number(r.stars)} stars" if r.stars is not None else None,
            r.buyer_country, r.date,
        ] if x)
        review_lines.append(f'- "{r.text.strip()}"' + (f" ({meta})" if meta else ""))

    body = _lines(
        "# Reviews and ratings",
        _labelled("Overall rating", f"{format_number(s.overall_rating)} out of 5"
                  if s.overall_rating is not None else None),
        _labelled("Total reviews", s.total_reviews
                  if s.total_reviews is not None else None),
        "\n## Star breakdown\n" + breakdown if breakdown else None,
        "\n## What buyers said\n" + "\n".join(review_lines) if review_lines else None,
    )

    if not (breakdown or review_lines or s.overall_rating is not None
            or s.total_reviews is not None):
        return None

    return _doc(seller_id, "reviews", f"{seller_id}__reviews",
                f"{seller_id}_reviews.md", body, profile.source_type)


def build_documents(profile: SellerProfile) -> List[dict]:
    """Every retrievable document for one seller."""
    docs = [bio_document(profile)]
    docs += [gig_document(profile, g, i) for i, g in enumerate(profile.gigs)]
    docs += [portfolio_document(profile, p, i)
             for i, p in enumerate(profile.portfolio)]
    docs.append(reviews_document(profile))
    return [d for d in docs if d]


# --- Human-readable export -------------------------------------------------

def render_markdown(profile: SellerProfile) -> str:
    """The whole profile as one markdown file.

    Written to `kb/profile_gigs/` on every save so a profile is still readable
    (and diffable in git) outside the app. It is an export, not an input --
    nothing parses it back.
    """
    header = (
        "---\n"
        "type: profile_export\n"
        f"seller_id: {profile.resolved_seller_id()}\n"
        f"source_type: {profile.source_type}\n"
        "---\n\n"
        "<!-- Generated by Fiverr Brain. Edits here are NOT read back:\n"
        "     the profile lives in data/fiverr_brain.sqlite3. Edit it in the\n"
        "     app's Profile onboarding mode. -->\n"
    )
    return header + "\n\n---\n\n".join(
        d["text"] for d in build_documents(profile)
    ) + "\n"
