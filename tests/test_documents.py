"""
Document assembly and the per-seller vector pipeline.

Two things are load-bearing here. The metadata has to carry the four keys the
brief names, because that is what makes seller filtering and citations
possible at all. And re-ingesting one seller has to leave every other seller
alone -- the failure mode is silent, and it corrupts answers rather than
crashing.
"""
import pytest

from src import config, documents, ingest
from src.schema import (
    About, BasicInfo, FAQ, Gig, Package, PortfolioItem, Review, ReviewSummary,
    SellerProfile, Skills,
)

REQUIRED_METADATA = {"sellerId", "sectionType", "gigId", "sourceType"}


def profile(seller_id="doc_test_seller", source_type="manual") -> SellerProfile:
    return SellerProfile(
        seller_id=seller_id,
        basic=BasicInfo(name="Doc Tester", username=seller_id,
                        country="Pakistan", languages=["English (fluent)"],
                        avg_response_time="1 hour"),
        about=About(bio="I build automations for small businesses."),
        skills=Skills(skills=["n8n", "Zapier"], tests=["English — 9/10"]),
        gigs=[
            Gig(gig_id="g1", title="I will build an n8n workflow",
                category="Programming & Tech",
                description="Production-ready workflows.",
                packages=[Package(tier="basic", name="Starter", price=50.0,
                                  delivery_days=3, revisions="1",
                                  features=["1 workflow"])],
                extras=["24h delivery +$40"],
                faqs=[FAQ(question="Support?", answer="14 days.")]),
            Gig(gig_id="g2", title="I will audit your automations",
                description="A written report on what is fragile."),
        ],
        portfolio=[PortfolioItem(title="Invoice automation",
                                 description="Saved four hours a week.",
                                 link="https://example.com")],
        reviews=[Review(text="Excellent work.", stars=5.0,
                        buyer_country="US", date="2 weeks ago")],
        review_summary=ReviewSummary(overall_rating=4.9, total_reviews=10,
                                     stars_5=9, stars_4=1),
        source_type=source_type,
    )


# --- Splitting into logical units -------------------------------------------

def test_one_document_per_logical_unit():
    """The brief: bio, each gig, each portfolio item, a reviews digest."""
    docs = documents.build_documents(profile())
    sections = [d["metadata"]["sectionType"] for d in docs]
    assert sections.count("bio") == 1
    assert sections.count("gig") == 2
    assert sections.count("portfolio") == 1
    assert sections.count("reviews") == 1
    assert len(docs) == 5


def test_reviews_are_one_digest_not_one_document_each():
    p = profile()
    p.reviews = [Review(text=f"Review {i}", stars=5.0) for i in range(20)]
    docs = documents.build_documents(p)
    assert sum(1 for d in docs if d["metadata"]["sectionType"] == "reviews") == 1


def test_every_document_carries_the_required_metadata():
    for doc in documents.build_documents(profile()):
        assert REQUIRED_METADATA <= set(doc["metadata"])
        assert doc["metadata"]["sellerId"] == "doc_test_seller"
        assert doc["metadata"]["sourceType"] == "manual"
        # Chroma rejects None in metadata, and a missing key cannot be matched
        # by a where filter.
        assert all(v is not None for v in doc["metadata"].values())


def test_gig_documents_carry_their_own_gig_id():
    docs = documents.build_documents(profile())
    gig_ids = {d["metadata"]["gigId"] for d in docs
               if d["metadata"]["sectionType"] == "gig"}
    assert gig_ids == {"g1", "g2"}
    non_gig = {d["metadata"]["gigId"] for d in docs
               if d["metadata"]["sectionType"] != "gig"}
    assert non_gig == {"N/A"}


def test_source_type_follows_the_profile():
    for doc in documents.build_documents(profile(source_type="ocr")):
        assert doc["metadata"]["sourceType"] == "ocr"


def test_document_ids_are_unique():
    ids = [d["id"] for d in documents.build_documents(profile())]
    assert len(ids) == len(set(ids))


# --- Content ----------------------------------------------------------------

def test_the_bio_document_holds_identity_and_skills():
    """'What languages do you speak' has to land somewhere retrievable."""
    doc = next(d for d in documents.build_documents(profile())
               if d["metadata"]["sectionType"] == "bio")
    text = doc["text"]
    for expected in ("Doc Tester", "English (fluent)", "Pakistan", "n8n",
                     "automations for small businesses", "1 hour"):
        assert expected in text


def test_a_gig_document_holds_its_packages_extras_and_faqs():
    doc = next(d for d in documents.build_documents(profile())
               if d["metadata"]["gigId"] == "g1")
    for expected in ("Starter", "$50", "3 day delivery", "1 revisions",
                     "1 workflow", "24h delivery +$40", "Support?", "14 days."):
        assert expected in doc["text"], expected


def test_the_reviews_digest_holds_the_breakdown_and_the_text():
    doc = next(d for d in documents.build_documents(profile())
               if d["metadata"]["sectionType"] == "reviews")
    assert "4.9 out of 5" in doc["text"]
    assert "5 star: 9 review(s)" in doc["text"]
    assert "Excellent work." in doc["text"]


def test_empty_sections_produce_no_document():
    """A document holding nothing but a heading matches weakly against
    everything and answers nothing."""
    assert documents.build_documents(SellerProfile()) == []

    only_bio = SellerProfile(seller_id="x", about=About(bio="Just a bio."))
    docs = documents.build_documents(only_bio)
    assert [d["metadata"]["sectionType"] for d in docs] == ["bio"]


def test_a_gig_with_no_content_is_skipped():
    p = profile()
    p.gigs.append(Gig(gig_id="empty"))
    assert not any(d["metadata"]["gigId"] == "empty"
                   for d in documents.build_documents(p))


# --- Markdown export --------------------------------------------------------

def test_the_markdown_export_says_it_is_not_read_back():
    """It used to be the source of truth. Anyone editing it now needs to know
    their edit goes nowhere."""
    text = documents.render_markdown(profile())
    assert "NOT read back" in text
    assert "doc_test_seller" in text
    assert "I will build an n8n workflow" in text


# --- The vector pipeline ----------------------------------------------------

@pytest.fixture
def indexed(brain):
    """Two sellers in the live index, cleaned up afterwards."""
    a = profile("pipe_alpha")
    b = profile("pipe_beta")
    b.about.bio = "I do something completely different: hand lettering."
    ingest.upsert_seller(a)
    ingest.upsert_seller(b)
    brain.refresh_collection()
    yield a, b
    ingest.delete_seller_vectors("pipe_alpha")
    ingest.delete_seller_vectors("pipe_beta")
    brain.refresh_collection()


def _chunks_for(brain, seller_id):
    return brain.client.get_collection(config.COLLECTION_NAME).get(
        where={"sellerId": seller_id}
    )


def test_upsert_indexes_a_seller(brain, indexed):
    assert _chunks_for(brain, "pipe_alpha")["ids"]


def test_reingesting_one_seller_leaves_the_others_untouched(brain, indexed):
    before = set(_chunks_for(brain, "pipe_beta")["ids"])
    alpha, _ = indexed
    alpha.about.bio = "Rewritten bio."
    ingest.upsert_seller(alpha)
    brain.refresh_collection()
    assert set(_chunks_for(brain, "pipe_beta")["ids"]) == before


def test_reingesting_does_not_duplicate(brain, indexed):
    alpha, _ = indexed
    before = len(_chunks_for(brain, "pipe_alpha")["ids"])
    ingest.upsert_seller(alpha)
    brain.refresh_collection()
    assert len(_chunks_for(brain, "pipe_alpha")["ids"]) == before


def test_a_shrinking_profile_does_not_leave_stale_chunks(brain, indexed):
    """Chunk ids depend on how the text splits, so Chroma's own upsert would
    leave the tail of a longer previous version behind."""
    alpha, _ = indexed
    alpha.gigs = []
    alpha.portfolio = []
    alpha.reviews = []
    alpha.review_summary = ReviewSummary()
    ingest.upsert_seller(alpha)
    brain.refresh_collection()

    got = _chunks_for(brain, "pipe_alpha")
    assert {m["sectionType"] for m in got["metadatas"]} == {"bio"}


def test_deleting_a_seller_removes_only_their_vectors(brain, indexed):
    ingest.delete_seller_vectors("pipe_alpha")
    brain.refresh_collection()
    assert not _chunks_for(brain, "pipe_alpha")["ids"]
    assert _chunks_for(brain, "pipe_beta")["ids"]


def test_kb_files_are_tagged_shared_not_owned_by_a_seller(brain):
    """Policies and SOPs belong to the business. Tagging them to a seller
    would make them vanish the moment another seller is selected."""
    got = brain.client.get_collection(config.COLLECTION_NAME).get(
        where={"layer": "sops"}
    )
    assert got["ids"], "expected the shipped SOP files to be indexed"
    assert all(m.get("sellerId", config.SHARED_SELLER_ID) == config.SHARED_SELLER_ID
               for m in got["metadatas"])


def test_an_upsert_with_nothing_to_index_warns_rather_than_silently_passing():
    warnings = []
    count = ingest.upsert_seller(SellerProfile(seller_id="empty_seller"),
                                 warn=warnings.append)
    assert count == 0
    assert warnings and "nothing to index" in warnings[0].lower()


def test_upsert_is_serialised_against_a_rebuild():
    """An upsert landing mid-rebuild would write into a collection that is
    about to be replaced."""
    ingest._REBUILD_LOCK.acquire()
    try:
        with pytest.raises(ingest.RebuildInProgress):
            ingest.upsert_seller(profile())
    finally:
        ingest._REBUILD_LOCK.release()


def test_an_index_predating_seller_metadata_is_flagged(brain, monkeypatch):
    """A version 1 index has no sellerId. A `where` clause cannot match a key
    that is not there, so once a seller exists every scoped question would
    silently come back 'I don't know'. Say so instead."""
    from src.rag import FiverrBrain

    real_metadata = brain.collection.metadata or {}

    class OldCollection:
        metadata = {k: v for k, v in real_metadata.items()
                    if k != "schema_version"}

        @staticmethod
        def count():
            return 8

    probe = FiverrBrain.__new__(FiverrBrain)
    probe.collection = OldCollection()
    warning = probe._check_index_model()

    assert warning and "reindex" in warning.lower()
    assert "sellerId" in warning


def test_a_current_index_is_not_flagged(brain):
    from src.rag import FiverrBrain

    class CurrentCollection:
        metadata = dict(ingest._index_metadata())

        @staticmethod
        def count():
            return 8

    probe = FiverrBrain.__new__(FiverrBrain)
    probe.collection = CurrentCollection()
    assert probe._check_index_model() is None


def test_the_generated_export_is_not_indexed_as_kb_content(brain, kb, monkeypatch):
    """The wizard writes a markdown export into kb/profile_gigs/. Indexing it
    as well as the store would file every seller twice -- once under their own
    sellerId, and once as shared content visible to every other seller."""
    from src import profile_setup as ps

    p = profile("export_dupe")
    ps.write_export(p)
    assert list(kb.glob("*.md")), "the export must actually have been written"

    chunks, metas, ids, kept = ingest._kb_file_records(lambda msg: None)
    assert not any("export_dupe" in str(m.get("source", "")) for m in metas)
    assert not any(path.name.endswith("_profile.md") for path in kept)


def test_hand_written_kb_files_are_still_indexed(kb):
    """The skip must key on the generated marker, not on living in that folder
    -- a hand-written note there is still knowledge."""
    (kb / "hand_written.md").write_text(
        "---\ntype: gig\n---\n\n# A note\n\nSomething the seller typed.",
        encoding="utf-8",
    )
    chunks, metas, ids, kept = ingest._kb_file_records(lambda msg: None)
    assert any(m["source"] == "hand_written.md" for m in metas)
