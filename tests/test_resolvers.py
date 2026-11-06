"""Unit tests for the fixed resolver registry (no Django required).

All network access is mocked; the tests feed canned API payloads through
the resolver functions and check the resulting publication dicts.
"""

import pytest
import requests

from coldfront_plugin_doi_resolver import resolvers
from coldfront_plugin_doi_resolver.resolvers import (
    _bibtex_to_pub_dict,
    get_registered_sources,
    get_resolver,
)

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_contains_integrated_ras_in_lookup_order():
    assert [entry.name for entry in get_registered_sources()] == [
        "crossref.org",
        "datacite.org",
        "doi.org",
        "adsabs",
    ]


def test_registry_entries_carry_source_url():
    entry = get_resolver("crossref.org")
    assert entry is not None
    assert entry.url == "https://doi.org/"
    entry = get_resolver("adsabs")
    assert entry is not None
    assert entry.url == "https://ui.adsabs.harvard.edu/"


def test_get_resolver_unknown_source():
    assert get_resolver("no-such-ra") is None


# ---------------------------------------------------------------------------
# crossref.org (habanero)
# ---------------------------------------------------------------------------


class FakeCrossref:
    """Stand-in for habanero's Crossref client."""

    mailto = None

    def __init__(self, mailto=None):
        type(self).mailto = mailto

    def works(self, ids):
        assert ids == "10.1038/nature12373"
        return {
            "status": "ok",
            "message-type": "work",
            "message": {
                "author": [
                    {"given": "G.", "family": "Kucsko", "sequence": "first"},
                    {"given": "P. C.", "family": "Maurer"},
                ],
                "issued": {"date-parts": [[2013, 7, 31]]},
                "title": ["Nanometre-scale thermometry in a living cell"],
                "container-title": ["Nature"],
            },
        }


def test_resolve_crossref(monkeypatch):
    monkeypatch.setattr(resolvers, "Crossref", FakeCrossref)
    pub = resolvers.resolve_crossref("10.1038/nature12373")
    assert pub == {
        "author": "Kucsko, G. and Maurer, P. C.",
        "year": "2013",
        "title": "Nanometre-scale thermometry in a living cell",
        "journal": "Nature",
        "unique_id": "10.1038/nature12373",
    }


def test_resolve_crossref_passes_polite_pool_mailto(monkeypatch):
    monkeypatch.setattr(resolvers, "CROSSREF_MAILTO", "admin@example.org")
    monkeypatch.setattr(resolvers, "Crossref", FakeCrossref)
    resolvers.resolve_crossref("10.1038/nature12373")
    assert FakeCrossref.mailto == "admin@example.org"


def test_resolve_crossref_fallbacks(monkeypatch):
    class NoMetadata(FakeCrossref):
        def works(self, ids):
            return {
                "message": {
                    # Consortium author without given/family name.
                    "author": [{"name": "CMS Collaboration"}],
                    "publisher": "Springer",
                    "issued": {"date-parts": [[]]},
                }
            }

    monkeypatch.setattr(resolvers, "Crossref", NoMetadata)
    pub = resolvers.resolve_crossref("10.1234/unknown")
    assert pub["author"] == "CMS Collaboration"
    assert pub["year"] == ""
    assert pub["title"] == ""
    assert pub["journal"] == "[no journal info from CROSSREF.ORG]"


# ---------------------------------------------------------------------------
# datacite.org (public REST API)
# ---------------------------------------------------------------------------


class FakeResponse:
    ok = False
    text = ""

    def __init__(self, ok=True, json_data=None, headers=None, text=None):
        self.ok = ok
        self.status_code = 200 if ok else 404
        self._json = json_data or {}
        self.headers = headers or {}
        if text is not None:
            self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error")


DATACITE_PAYLOAD = {
    "data": {
        "attributes": {
            "creators": [{"name": "Smith, John"}, {"name": "Doe, Jane"}],
            "publicationYear": 2015,
            "titles": [{"title": "Minimal Test Case"}],
            "container": {"title": "Scientific Data"},
        }
    }
}


def test_resolve_datacite(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return FakeResponse(json_data=DATACITE_PAYLOAD)

    monkeypatch.setattr(resolvers.requests, "get", fake_get)
    pub = resolvers.resolve_datacite("10.5281/zenodo.1234")
    assert calls == ["https://api.datacite.org/dois/10.5281/zenodo.1234"]
    assert pub == {
        "author": "Smith, John and Doe, Jane",
        "year": "2015",
        "title": "Minimal Test Case",
        "journal": "Scientific Data",
        "unique_id": "10.5281/zenodo.1234",
    }


def test_resolve_datacite_http_error(monkeypatch):
    monkeypatch.setattr(
        resolvers.requests, "get", lambda url, timeout=None: FakeResponse(ok=False)
    )
    assert resolvers.resolve_datacite("10.5281/zenodo.missing") is None


def test_resolve_datacite_journal_fallback(monkeypatch):
    payload = {
        "data": {
            "attributes": {
                "creators": [],
                "publicationYear": 2020,
                "titles": [],
            }
        }
    }
    monkeypatch.setattr(
        resolvers.requests,
        "get",
        lambda url, timeout=None: FakeResponse(json_data=payload),
    )
    pub = resolvers.resolve_datacite("10.5281/zenodo.1234")
    assert pub["author"] == ""
    assert pub["title"] == ""
    assert pub["journal"] == "[no journal info from DATACITE.ORG]"


# ---------------------------------------------------------------------------
# doi.org (content negotiation, CSL-JSON)
# ---------------------------------------------------------------------------


CSL_JSON_PAYLOAD = {
    "author": [
        {"given": "Ada", "family": "Lovelace"},
        {"given": "Alan", "family": "Turing"},
    ],
    "issued": {"date-parts": [[1843]]},
    "title": "Notes on the Analytical Engine",
    "container-title": "Scientific Memoirs",
    "publisher": "Richard and John E. Taylor",
}


def test_resolve_doi_org(monkeypatch):
    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        # Slashes are preserved (safe="/:"), only truly unsafe
        # characters would be percent-encoded.
        assert url == "https://doi.org/10.1234/safe/chars"
        assert headers["Accept"] == "application/vnd.citationstyles.csl+json"
        return FakeResponse(
            json_data=CSL_JSON_PAYLOAD,
            headers={"Content-Type": "application/vnd.citationstyles.csl+json"},
        )

    monkeypatch.setattr(resolvers.requests, "get", fake_get)
    pub = resolvers.resolve_doi_org("10.1234/safe/chars")
    assert pub == {
        "author": "Lovelace, Ada and Turing, Alan",
        "year": "1843",
        "title": "Notes on the Analytical Engine",
        "journal": "Scientific Memoirs",
        "unique_id": "10.1234/safe/chars",
    }


def test_resolve_doi_org_non_json_response(monkeypatch):
    monkeypatch.setattr(
        resolvers.requests,
        "get",
        lambda url, headers=None, timeout=None, allow_redirects=None: FakeResponse(
            headers={"Content-Type": "text/html"}
        ),
    )
    assert resolvers.resolve_doi_org("10.1234/foo") is None


def test_resolve_doi_org_http_error(monkeypatch):
    monkeypatch.setattr(
        resolvers.requests,
        "get",
        lambda url, headers=None, timeout=None, allow_redirects=None: FakeResponse(
            ok=False
        ),
    )
    assert resolvers.resolve_doi_org("10.1234/foo") is None


def test_resolve_doi_org_publisher_as_author(monkeypatch):
    payload = dict(CSL_JSON_PAYLOAD)
    del payload["author"]
    monkeypatch.setattr(
        resolvers.requests,
        "get",
        lambda url, headers=None, timeout=None, allow_redirects=None: FakeResponse(
            json_data=payload,
            headers={"Content-Type": "application/vnd.citationstyles.csl+json"},
        ),
    )
    pub = resolvers.resolve_doi_org("10.1234/foo")
    assert pub["author"] == "Richard and John E. Taylor"


# ---------------------------------------------------------------------------
# adsabs (BibTeX export)
# ---------------------------------------------------------------------------

ADS_BIBTEX = """@ARTICLE{2013ApJS..204...19W,
       author = {{Woodruff}, {R.~A.} and {McKee}, {C.~F.}},
        title = "{On the Relationship Between {SCUBA} and {MIPS}}",
      journal = {\\textquotesingle{}The Astrophysical Journal Supplement Series\\textquotesingle{}},
         year = 2013,
}"""


def test_resolve_adsabs(monkeypatch):
    def fake_get(url, timeout=None):
        assert "bibcode=2013ApJS..204...19W" in url
        assert "data_type=BIBTEX" in url
        return FakeResponse(text=ADS_BIBTEX)

    monkeypatch.setattr(resolvers.requests, "get", fake_get)
    pub = resolvers.resolve_adsabs("2013ApJS..204...19W")
    assert pub["author"] == "Woodruff, R.~A. and McKee, C.~F."
    assert pub["year"] == "2013"
    assert "SCUBA" in pub["title"]
    assert pub["journal"].startswith("'")  # textquotesingle replaced by '
    assert pub["unique_id"] == "2013ApJS..204...19W"


def test_resolve_adsabs_http_error(monkeypatch):
    response = FakeResponse(ok=False)
    monkeypatch.setattr(resolvers.requests, "get", lambda url, timeout=None: response)
    with pytest.raises(requests.HTTPError):
        resolvers.resolve_adsabs("not-a-bibcode")


# ---------------------------------------------------------------------------
# BibTeX parsing helpers
# ---------------------------------------------------------------------------


def test_bibtex_to_pub_dict_journal_fallback():
    pub = _bibtex_to_pub_dict(
        "@misc{foo,\n  author = {Doe, Jane},\n  title = {Some Dataset},\n  year = 2021,\n}",
        "10.1234/foo",
        "adsabs",
    )
    assert pub["journal"] == "[no journal info from ADSABS]"


def test_bibtex_to_pub_dict_no_entries():
    assert _bibtex_to_pub_dict("not bibtex at all", "10.1234/foo", "adsabs") is None


def test_bibtex_to_pub_dict_strips_braces_and_entities():
    # LaTeX entities appear with one or two backslashes depending on the
    # export source, optionally with an empty argument; all variants are
    # replaced.
    pub = _bibtex_to_pub_dict(
        "@article{foo, author = {Doe, J{\\textquotesingle}ane},"
        " title = {A {Study}}, journal = {J.~Foo}, year = 2020}",
        "10.1234/foo",
        "crossref.org",
    )
    assert pub["author"] == "Doe, J'ane"
    assert pub["title"] == "A Study"
    assert pub["journal"] == "J.~Foo"
    assert pub["year"] == "2020"

    pub = _bibtex_to_pub_dict(
        "@article{bar, author = {Doe, J{\\\\textquotesingle{}ane}},"
        " title = {A {Study}}, journal = {J.~Foo}, year = 2020}",
        "10.1234/bar",
        "crossref.org",
    )
    assert pub["author"] == "Doe, J'ane"
