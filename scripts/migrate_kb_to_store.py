"""
One-time import of the pre-SQLite knowledge base into the profile store.

Before the schema change, a seller's profile and gigs lived as markdown under
`kb/profile_gigs/`, with one `## Heading` per field. This reads those files,
maps them onto the current models, and writes them into
`data/fiverr_brain.sqlite3` so nothing that was typed in by hand is lost.

The old parsers live here rather than in `src/`: they understand a format the
app no longer writes, and keeping them in the main modules would leave two
readers for a file that now has only one writer.

    python scripts/migrate_kb_to_store.py            # preview, writes nothing
    python scripts/migrate_kb_to_store.py --apply    # import
    python scripts/migrate_kb_to_store.py --apply --reindex

After a successful import the source files are renamed to `*.md.imported` so
the same content is not indexed twice -- once from the file and once from the
store. Nothing is deleted. Pass --keep-files to skip the rename, and expect
duplicate chunks until you remove them yourself.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, store                                    # noqa: E402
from src.ingest import parse_frontmatter                         # noqa: E402
from src.schema import (                                         # noqa: E402
    About, BasicInfo, Gig, Package, SellerProfile, Skills,
    derive_gig_id, derive_seller_id,
)

LEGACY_PROFILE_FILENAME = "seller_profile.md"

# Old "## Heading" -> where the value goes now. Includes the aliases the
# previous wizard accepted, so a profile written by an even earlier version
# still lands in the right place.
PROFILE_SECTIONS = {
    "name": "name",
    "headline": "headline",
    "level": "level",
    "bio": "bio",
    "about": "bio",
    "professional description": "bio",
    "description": "bio",
    "skills": "skills",
    "specialties": "skills",
    "specialties & skills": "skills",
    "languages": "languages",
    "education": "education",
    "certifications": "certifications",
    "certificates": "certifications",
    "response time": "avg_response_time",
    "availability": "avg_response_time",
    "working style": "working_style",
}

GIG_SECTIONS = {
    "title": "title",
    "category": "category",
    # Several headings feed the description; they are concatenated in the
    # order they appear rather than overwriting each other.
    "description": "description",
    "what's delivered": "description",
    "whats delivered": "description",
    "tagline": "description",
    "seller pitch": "description",
    "experience": "description",
    "packages": "packages",
    "pricing": "packages",
    "pricing tiers": "packages",
    "price": "packages",
    "delivery time": "delivery_time",
    "requirements": "requirements",
    "how it works": "requirements",
    "extras": "extras",
    "gig extras": "extras",
    "faq": "faqs",
    "faqs": "faqs",
}

LIST_KEYS = {"skills", "languages", "education", "certifications", "extras"}

# Headings whose text is concatenated rather than replaced when a file uses
# more than one of them.
APPEND_KEYS = {"description"}


def split_lines(value):
    out = []
    for line in str(value or "").splitlines():
        item = line.strip().lstrip("-*•").strip()
        if item and item not in out:
            out.append(item)
    return out


def parse_sections(text: str, mapping: dict) -> dict:
    """Read '## Heading' blocks into a flat dict, ignoring unknown headings."""
    _, body = parse_frontmatter(text)
    data, current, buffer, heading_text = {}, None, [], None

    def flush():
        if not current or not buffer:
            return
        raw = "\n".join(buffer).strip()
        if not raw:
            return
        if current in LIST_KEYS:
            data[current] = data.get(current, []) + split_lines(raw)
        elif current in APPEND_KEYS and data.get(current):
            # Keep the heading so "Tagline" and "What's delivered" don't merge
            # into one unattributed wall of text.
            data[current] += f"\n\n**{heading_text}**\n{raw}"
        else:
            data[current] = raw

    for line in body.splitlines():
        heading = re.match(r"^##\s+(.*?)\s*$", line)
        if heading:
            flush()
            label = heading.group(1).strip()
            current = mapping.get(label.lower())
            heading_text = label
            buffer = []
            continue
        if current:
            buffer.append(line)
    flush()

    if "name" not in data:
        m = re.search(r"^#\s+Seller Profile:\s*(.+)$", body, re.MULTILINE)
        if m:
            data["name"] = m.group(1).strip()
    if "title" in mapping.values() and "title" not in data:
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if m:
            # The files write "# Gig: I will ..." -- the label is not part of
            # the title the buyer sees.
            data["title"] = re.sub(r"^gig:\s*", "", m.group(1).strip(),
                                   flags=re.IGNORECASE)
    return data


# The old pricing box came in two shapes. A markdown table:
#   | Tier | Price (PKR) | Delivery Time | Revisions |
#   | Basic | 11,667.42 | 2-day delivery | 1 Revision |
# or free text, one tier per line:
#   Basic $50 - 1 workflow, 3 nodes, 1 revision, 3 days
_TIER_RE = re.compile(r"^\s*(basic|standard|premium)\b[\s:—-]*(.*)$", re.IGNORECASE)
_PRICE_RE = re.compile(r"[$€£]?\s*([\d,]+(?:\.\d+)?)")
_DAYS_RE = re.compile(r"(\d+)\s*[-\s]?\s*(?:day|days|d)\b", re.IGNORECASE)
_REV_RE = re.compile(r"(\d+|unlimited)\s*revision", re.IGNORECASE)
_NO_REV_RE = re.compile(r"\bno\s+revisions?\b", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"\(([A-Z]{3})\)|\b(USD|PKR|EUR|GBP|INR|AUD|CAD)\b")


def _to_days(text: str):
    m = _DAYS_RE.search(str(text or ""))
    return int(m.group(1)) if m else None


def _to_revisions(text: str):
    text = str(text or "")
    if _NO_REV_RE.search(text):
        return "0"
    m = _REV_RE.search(text)
    return m.group(1) if m else None


def _table_rows(raw_text: str):
    """(header_cells, [row_cells]) for a markdown table, or (None, [])."""
    rows = []
    header = None
    for line in str(raw_text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # the |---|---| separator
        if header is None:
            header = cells
        else:
            rows.append(cells)
    return header, rows


def parse_packages(raw_text: str, delivery_time: str = "") -> list:
    """Best-effort structuring of the old pricing box.

    Anything not confidently recognised is left in `features` verbatim rather
    than guessed at -- a wrong price in the knowledge base is worse than an
    unparsed line a human can still read. Currency is recorded as written; it
    is never converted, because a converted number cannot be checked against
    the source.
    """
    raw_text = str(raw_text or "")
    header, rows = _table_rows(raw_text)

    if header and rows:
        currency = None
        joined_header = " ".join(header)
        m = _CURRENCY_RE.search(joined_header)
        if m:
            currency = m.group(1) or m.group(2)

        packages = []
        for cells in rows:
            tier_match = _TIER_RE.match(cells[0] if cells else "")
            if not tier_match:
                continue
            rest = cells[1:]

            price = None
            if len(rest) > 0:
                pm = _PRICE_RE.search(rest[0])
                if pm:
                    price = float(pm.group(1).replace(",", ""))

            packages.append(Package(
                tier=tier_match.group(1).lower(),
                price=price,
                currency=currency,
                delivery_days=_to_days(rest[1]) if len(rest) > 1 else None,
                revisions=_to_revisions(rest[2]) if len(rest) > 2 else None,
                features=[c for c in rest[3:] if c],
            ))
        if packages:
            return packages

    packages = []
    for line in raw_text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line or line.startswith("|"):
            continue
        m = _TIER_RE.match(line)
        if not m:
            continue
        tier, rest = m.group(1).lower(), m.group(2).strip()

        price = re.search(r"[$€£]\s*([\d,]+(?:\.\d+)?)", rest)
        days = _DAYS_RE.search(rest)
        revs = _REV_RE.search(rest)

        leftover = rest
        for match in (price, days, revs):
            if match:
                leftover = leftover.replace(match.group(0), " ")
        features = [f.strip(" ,;–—-") for f in re.split(r"[,;]", leftover)]

        packages.append(Package(
            tier=tier,
            price=float(price.group(1).replace(",", "")) if price else None,
            currency="USD" if price and "$" in price.group(0) else None,
            delivery_days=int(days.group(1)) if days else _to_days(delivery_time),
            revisions=_to_revisions(rest),
            features=[f for f in features if f],
        ))
    return packages


def build_profile_from_kb(folder: Path):
    """(profile, source_paths) or (None, []) when there is nothing to import."""
    profile_path = folder / LEGACY_PROFILE_FILENAME
    sources = []

    raw = {}
    if profile_path.exists():
        raw = parse_sections(profile_path.read_text(encoding="utf-8"),
                             PROFILE_SECTIONS)
        sources.append(profile_path)

    seller_id = derive_seller_id(None, raw.get("name"))

    gigs = []
    for path in sorted(folder.glob("*.md")):
        if path.name == LEGACY_PROFILE_FILENAME:
            continue
        text = path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)
        if meta.get("type") in ("profile", "profile_export"):
            continue
        g = parse_sections(text, GIG_SECTIONS)
        if not (g.get("title") or g.get("description")):
            continue

        packages = parse_packages(g.get("packages", ""), g.get("delivery_time", ""))
        extras = g.get("extras") or []
        # The old form had a free-text "Requirements" box with no home in the
        # new schema. Appending it to the description keeps it retrievable
        # instead of dropping it on the floor.
        description = g.get("description", "")
        if g.get("requirements"):
            description = (description + "\n\n**What I need from you:**\n"
                           + g["requirements"]).strip()
        # An unparsed pricing box would otherwise be lost entirely.
        if g.get("packages") and not packages:
            description = (description + "\n\n**Pricing (unstructured, from the "
                           "old knowledge base):**\n" + g["packages"]).strip()

        gigs.append(Gig(
            gig_id=derive_gig_id(seller_id, g.get("title"), len(gigs)),
            title=g.get("title"),
            # The old files put the category in the frontmatter, not in a
            # "## Category" section.
            category=g.get("category") or meta.get("category") or None,
            description=description, packages=packages,
            extras=extras if isinstance(extras, list) else split_lines(extras),
        ))
        sources.append(path)

    if not raw and not gigs:
        return None, []

    profile = SellerProfile(
        seller_id=seller_id,
        basic=BasicInfo(
            name=raw.get("name"), headline=raw.get("headline"),
            level=raw.get("level"), languages=raw.get("languages") or [],
            avg_response_time=raw.get("avg_response_time"),
        ),
        about=About(bio=raw.get("bio"), working_style=raw.get("working_style")),
        skills=Skills(
            skills=raw.get("skills") or [],
            education=raw.get("education") or [],
            certifications=raw.get("certifications") or [],
        ),
        gigs=gigs,
        source_type="manual",
    )
    return profile, sources


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write. Without it this is a dry run.")
    ap.add_argument("--reindex", action="store_true",
                    help="Rebuild the vector index after importing.")
    ap.add_argument("--keep-files", action="store_true",
                    help="Do not rename the imported markdown files.")
    args = ap.parse_args()

    folder = Path(config.KB_FOLDERS["profile_gigs"])
    if not folder.exists():
        print(f"Nothing to do: {folder} does not exist.")
        return 0

    profile, sources = build_profile_from_kb(folder)
    if profile is None:
        print(f"Nothing to import: no legacy profile or gig files in {folder}.")
        return 0

    seller_id = profile.resolved_seller_id()
    print(f"Seller id      : {seller_id}")
    print(f"Name           : {profile.basic.name or '(none)'}")
    print(f"Skills         : {len(profile.skills.skills)}")
    print(f"Languages      : {len(profile.basic.languages)}")
    print(f"Gigs           : {len(profile.gigs)}")
    for g in profile.gigs:
        tiers = ", ".join(p.tier for p in g.packages if p.tier) or "none parsed"
        print(f"  - {g.title}  (packages: {tiers})")
    print(f"Source files   : {len(sources)}")

    if store.load_seller(seller_id) is not None:
        print(f"\nRefusing to overwrite: seller '{seller_id}' is already in the "
              f"store. Delete it in the app first if you want to re-import.")
        return 1

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to import.")
        return 0

    from src import profile_setup

    profile_setup.save_profile(profile, validate=False)
    print(f"\nImported into {config.PROFILE_DB}")

    if not args.keep_files:
        for path in sources:
            renamed = path.with_name(path.name + ".imported")
            path.rename(renamed)
            print(f"  renamed {path.name} -> {renamed.name}")
    else:
        print("  source files kept — expect duplicate chunks until you remove them.")

    if args.reindex:
        from src import ingest

        print("\nRebuilding the index...")
        print(f"Indexed {ingest.build_index(verbose=False)} chunks.")
    else:
        print("\nRun `python scripts/reindex.py` to make this searchable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
