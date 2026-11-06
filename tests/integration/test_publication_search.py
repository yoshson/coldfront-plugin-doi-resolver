"""Integration tests: the plugin inside a real ColdFront instance.

The resolver *functions* are replaced with canned fakes (their network
behaviour is covered by the unit tests); these tests verify the glue:
ColdFront's ``PublicationSearchResultView`` is patched at startup, uses
the fixed registry, and creates/reuses ``PublicationSource`` rows on
demand instead of consulting seeded database entries.
"""

import pytest
from coldfront.core.publication.models import PublicationSource
from coldfront.core.publication.views import PublicationSearchResultView
from django.urls import reverse

from coldfront_plugin_doi_resolver import views as plugin_views
from coldfront_plugin_doi_resolver.resolvers import ResolverEntry
from coldfront_plugin_doi_resolver.views import PublicationSearchResultMixin

PUB_DICT = {
    "author": "Kucsko, G. and Maurer, P. C.",
    "year": "2013",
    "title": "Nanometre-scale thermometry in a living cell",
    "journal": "Nature",
    "unique_id": "10.1038/nature12373",
}


@pytest.fixture
def crossref_entry(monkeypatch):
    """A registry containing a single succeeding crossref.org resolver."""
    entry = ResolverEntry(
        name="crossref.org",
        url="https://doi.org/",
        resolve=lambda unique_id: dict(PUB_DICT, unique_id=unique_id),
    )
    monkeypatch.setattr(plugin_views, "get_registered_sources", lambda: [entry])
    return entry


def test_publication_search_view_is_patched():
    """ready() replaced upstream's hard-coded Crossref/ADS lookup."""
    assert (
        PublicationSearchResultView._search_id
        is PublicationSearchResultMixin._search_id
    )


def test_search_id_uses_fixed_registry(db, crossref_entry):
    view = PublicationSearchResultView()
    pub_dict = view._search_id("10.1038/nature12373")

    assert pub_dict["title"] == PUB_DICT["title"]
    # The PublicationSource row is created on demand, not read from a
    # pre-seeded table.
    source = PublicationSource.objects.get(name="crossref.org")
    assert pub_dict["source_pk"] == source.pk
    assert source.url == "https://doi.org/"


def test_search_id_reuses_existing_publication_source(db, crossref_entry):
    # A pre-existing row (e.g. created by a previous search, or with a
    # hand-edited url) must be reused instead of duplicated.
    source = PublicationSource.objects.create(
        name="crossref.org", url="https://example.org/other-url"
    )

    view = PublicationSearchResultView()
    pub_dict = view._search_id("10.1038/nature12373")

    assert pub_dict["source_pk"] == source.pk
    assert PublicationSource.objects.filter(name="crossref.org").count() == 1


def test_search_id_first_resolver_wins(db, monkeypatch):
    def boom(unique_id):
        raise RuntimeError("should not be reached")

    entries = [
        ResolverEntry(name="first", url=None, resolve=lambda uid: dict(PUB_DICT)),
        ResolverEntry(name="second", url=None, resolve=boom),
    ]
    monkeypatch.setattr(plugin_views, "get_registered_sources", lambda: entries)

    view = PublicationSearchResultView()
    pub_dict = view._search_id("anything")

    assert pub_dict["source_pk"] == PublicationSource.objects.get(name="first").pk


def test_search_id_continues_after_resolver_error(db, monkeypatch):
    def boom(unique_id):
        raise RuntimeError("resolver down")

    entries = [
        ResolverEntry(name="broken", url=None, resolve=boom),
        ResolverEntry(name="working", url=None, resolve=lambda uid: dict(PUB_DICT)),
    ]
    monkeypatch.setattr(plugin_views, "get_registered_sources", lambda: entries)

    view = PublicationSearchResultView()
    pub_dict = view._search_id("anything")

    assert pub_dict["source_pk"] == PublicationSource.objects.get(name="working").pk


def test_search_id_returns_false_when_all_resolvers_fail(db, monkeypatch):
    def boom(unique_id):
        raise RuntimeError("resolver down")

    entries = [
        ResolverEntry(name="broken", url=None, resolve=boom),
        ResolverEntry(name="empty", url=None, resolve=lambda uid: None),
    ]
    monkeypatch.setattr(plugin_views, "get_registered_sources", lambda: entries)

    view = PublicationSearchResultView()
    assert view._search_id("anything") is False
    # Only the "manual" row seeded by ColdFront's migrations remains;
    # no source rows were created by the failed search.
    assert set(PublicationSource.objects.values_list("name", flat=True)) == {"manual"}


def test_publication_search_result_view_end_to_end(pi_client, project, crossref_entry):
    """The real URLconf/view/template flow with the patched lookup."""
    url = reverse("publication-search-result", kwargs={"project_pk": project.pk})
    response = pi_client.post(url, {"search_id": "10.1038/nature12373"})

    assert response.status_code == 200
    assert b"Nanometre-scale thermometry in a living cell" in response.content
    assert PublicationSource.objects.filter(name="crossref.org").exists()
