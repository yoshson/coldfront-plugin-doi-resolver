"""Fixed registry of publication-source resolvers.

How it works
------------
Each registration agency (RA) integrated with this plugin is defined *in
code* as an entry in the registry below -- no database rows decide which
resolvers run.  Each entry carries

* ``name``    -- the name of the ColdFront ``PublicationSource`` it maps to,
* ``url``     -- the URL stored on that ``PublicationSource`` (informational),
* ``resolve`` -- the function fetching the metadata.

Interface contract for every resolver function:

    def my_resolver(unique_id: str) -> dict | None

* *unique_id* -- the identifier the user typed (DOI, bibcode, ...).
* **Return** a dict with at least ``author``, ``year``, ``title``,
  ``journal``, ``unique_id`` -- or ``None`` / raise on failure.

ColdFront still requires every ``Publication`` to reference a
``PublicationSource`` row, so the view integration creates the matching
row on demand (``get_or_create``) instead of relying on seeded entries.

Adding a new resolver
---------------------
Just add a decorated function anywhere in this file (or import this module
and decorate in another module that is imported at startup)::

    @publication_resolver("my-ra.org", "https://my-ra.org/")
    def resolve_my_ra(unique_id):
        ...
        return {"author": ..., "year": ..., "title": ...,
                "journal": ..., "unique_id": unique_id}
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import requests
from habanero import Crossref

logger = logging.getLogger(__name__)

# Optional contact address for Crossref's "polite API" pool; populated from
# the DOI_RESOLVER_CROSSREF_MAILTO setting by the app config (keeping this
# module free of Django imports so it stays unit-testable without Django).
CROSSREF_MAILTO: str | None = None

# Personal ADS API token; populated from the DOI_RESOLVER_ADSABS_TOKEN
# setting by the app config. The ADS API requires authentication -- the
# legacy anonymous BibTeX endpoint is dead (see resolve_adsabs) -- so the
# adsabs resolver is skipped when no token is configured.
ADSABS_TOKEN: str | None = None

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolverEntry:
    """A publication source integrated with this plugin, defined in code."""

    name: str
    url: str | None
    resolve: Callable[[str], dict | None]


_registry: list[ResolverEntry] = []


def publication_resolver(source_name: str, source_url: str | None = None):
    """Register a resolver function for a publication source name."""

    def decorator(func):
        _registry.append(ResolverEntry(name=source_name, url=source_url, resolve=func))
        return func

    return decorator


def get_resolver(source_name: str) -> ResolverEntry | None:
    """Return the registry entry for *source_name*, or ``None``."""
    return next((e for e in _registry if e.name == source_name), None)


def get_registered_sources() -> list[ResolverEntry]:
    """Return all integrated sources, in registration (= lookup) order."""
    return list(_registry)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _no_journal(source_name: str) -> str:
    """Fallback journal value, clearly indicating that data was absent."""
    return f"[no journal info from {source_name.upper()}]"


def _first(value) -> str:
    """Return the first element of a list, or the value itself."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _author_name(author: dict) -> str:
    """Format one CSL-JSON author as ``Family, Given`` (or bare name)."""
    if author.get("family") or author.get("given"):
        return f"{author.get('family', '')}, {author.get('given', '')}".strip(", ")
    return author.get("name", "")


def _csl_to_pub_dict(data: dict, unique_id: str, source_name: str) -> dict:
    """Normalise a CSL-JSON document (or a Crossref API ``message``) to a
    publication dict as expected by ColdFront's publication search."""
    authors = data.get("author", [])
    if authors:
        author_str = " and ".join(_author_name(a) for a in authors)
    else:
        author_str = _first(data.get("publisher", ""))

    issued = data.get("issued", {})
    date_parts = issued.get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

    journal = _first(data.get("container-title", "")) or _no_journal(source_name)

    return {
        "author": author_str,
        "year": year,
        "title": _first(data.get("title", "")),
        "journal": journal,
        "unique_id": unique_id,
    }


# ---------------------------------------------------------------------------
# resolver functions
#
# The definition order below is the lookup order used by the view
# integration: specific RAs first, the generic doi.org fallback (which
# works for *all* RAs) after them, non-DOI sources last.
# ---------------------------------------------------------------------------


@publication_resolver("crossref.org", "https://doi.org/")
def resolve_crossref(unique_id: str) -> dict | None:
    """Resolve a DOI via the Crossref API (using habanero)."""
    client = Crossref(mailto=CROSSREF_MAILTO)
    result = client.works(ids=unique_id)
    return _csl_to_pub_dict(result.get("message", {}), unique_id, "crossref.org")


@publication_resolver("datacite.org", "https://doi.org/")
def resolve_datacite(unique_id: str) -> dict | None:
    """Resolve a DOI via DataCite's public REST API.

    The ``datacite`` package is deliberately *not* used: its REST client
    targets DOI *management* (minting, updating, hiding) and requires
    account credentials plus a fixed DOI prefix, which makes it unsuitable
    for anonymously resolving arbitrary DOIs. The public REST endpoint
    used below needs no authentication.
    """
    url = f"https://api.datacite.org/dois/{quote(unique_id, safe='/:')}"
    r = requests.get(url, timeout=8)
    if not r.ok:
        return None

    attrs = r.json().get("data", {}).get("attributes", {})

    creators = attrs.get("creators", [])
    author_str = " and ".join(c.get("name", "") for c in creators) if creators else ""

    year = str(attrs.get("publicationYear", ""))

    titles = attrs.get("titles", [])
    title = titles[0].get("title", "") if titles else ""

    container = attrs.get("container", {})
    if container:
        journal = container.get("title", _no_journal("datacite.org"))
    else:
        journal = _no_journal("datacite.org")

    return {
        "author": author_str,
        "year": year,
        "title": title,
        "journal": journal,
        "unique_id": unique_id,
    }


@publication_resolver("doi.org", "https://doi.org/")
def resolve_doi_org(unique_id: str) -> dict | None:
    """Resolve a DOI via doi.org content negotiation (works for *all* RAs)."""
    r = requests.get(
        f"https://doi.org/{quote(unique_id, safe='/:')}",
        headers={"Accept": "application/vnd.citationstyles.csl+json"},
        timeout=8,
        allow_redirects=True,
    )
    if not (r.ok and "json" in r.headers.get("Content-Type", "")):
        return None

    return _csl_to_pub_dict(r.json(), unique_id, "doi.org")


@publication_resolver("adsabs", "https://ui.adsabs.harvard.edu/")
def resolve_adsabs(unique_id: str) -> dict | None:
    """Resolve a bibcode via the ADS API (requires a personal API token).

    The legacy anonymous BibTeX endpoint
    (``adsabs.harvard.edu/cgi-bin/nph-bib_query``) is dead: it redirects
    to the ADS UI, which is fronted by bot protection, so it no longer
    returns BibTeX. The supported ADS API needs a free personal token
    (https://ui.adsabs.harvard.edu/user/settings/token), configured via
    the ``DOI_RESOLVER_ADSABS_TOKEN`` setting. Without a token this
    resolver returns ``None`` and the search moves on.
    """
    if not ADSABS_TOKEN:
        logger.info(
            "adsabs resolver skipped: no ADS API token configured "
            "(set DOI_RESOLVER_ADSABS_TOKEN in your ColdFront settings)."
        )
        return None

    # Guard the Solr quoted phrase below against quote injection.
    if '"' in unique_id:
        return None

    r = requests.get(
        "https://api.adsabs.harvard.edu/v1/search/query",
        params={
            "q": f'bibcode:"{unique_id}"',
            "fl": "author,title,year,pub",
            "rows": 1,
        },
        headers={"Authorization": f"Bearer {ADSABS_TOKEN}"},
        timeout=8,
    )
    r.raise_for_status()

    docs = r.json().get("response", {}).get("docs", [])
    if not docs:
        return None
    doc = docs[0]

    authors = doc.get("author") or []
    titles = doc.get("title") or []

    return {
        "author": " and ".join(authors),
        "year": str(doc.get("year") or ""),
        "title": titles[0] if titles else "",
        "journal": doc.get("pub") or _no_journal("adsabs"),
        "unique_id": unique_id,
    }
