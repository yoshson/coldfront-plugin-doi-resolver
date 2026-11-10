# coldfront-plugin-doi-resolver

A [ColdFront](https://coldfront.readthedocs.io/) plugin that resolves
publication metadata in ColdFront's *add publication* search from DOIs and
bibcodes — via a **fixed, code-defined registry of registration agencies
(RAs)** instead of the hard-coded Crossref/ADS lookup (and the
`PublicationSource` database rows) that stock ColdFront uses.

## How it works

Stock ColdFront decides which metadata sources to try from the
`PublicationSource` rows in its database and only knows Crossref (via the
`doi2bib` package) and ADS. This plugin replaces the lookup behind
`PublicationSearchResultView._search_id` with a resolver registry defined
entirely in code (`coldfront_plugin_doi_resolver/resolvers.py`):

| Source name   | Integration | Lookup order |
| ------------- | ----------- | ----------- |
| `crossref.org` | Crossref API via [habanero](https://pypi.org/project/habanero/) | 1 |
| `datacite.org` | DataCite public REST API | 2 |
| `doi.org`      | doi.org content negotiation (CSL-JSON) — works for *all* RAs | 3 |
| `adsabs`       | ADS API — requires a personal API token | 4 |

The first resolver that returns metadata wins. No database rows decide
which resolvers run, and nothing needs to be seeded: ColdFront still
requires every `Publication` to reference a `PublicationSource` row, so the
plugin creates the matching row **on demand** (`get_or_create` by name)
when a resolver succeeds. Pre-existing rows with the same name are reused
as-is — which also means ColdFront's own
`add_default_publication_sources` command (which wipes the
`PublicationSource` table) is harmless.

### Why habanero instead of doi2bib

`doi2bib` fetches BibTeX from Crossref and had to be pinned to work
around API changes in its `bibtexparser` dependency. [habanero](https://pypi.org/project/habanero/)
is a maintained Crossref API client that returns structured JSON — no
BibTeX detour for Crossref, and no `doi2bib` dependency.

### Why *not* the `datacite` package

The [datacite](https://pypi.org/project/datacite/) package looks like the
obvious choice, but its REST client targets DOI *management* (minting,
updating, hiding DOIs) and requires account credentials plus a fixed DOI
prefix — it is not sensible for anonymously resolving arbitrary DataCite
DOIs. The plugin therefore calls DataCite's public REST endpoint
(`https://api.datacite.org/dois/<doi>`) directly, which needs no
authentication.

### Why the ADS resolver needs a token

Earlier versions (and stock ColdFront) fetched BibTeX for a bibcode from
ADS's anonymous legacy endpoint
(`adsabs.harvard.edu/cgi-bin/nph-bib_query`). That endpoint is dead: it
redirects to the ADS UI, which is fronted by bot protection, so every
bibcode lookup silently failed. The supported replacement is the
[ADS API](https://ui.adsabs.harvard.edu/help/api/), which requires a
**free personal API token** (create one at
[ADS user settings](https://ui.adsabs.harvard.edu/user/settings/token))
configured via the `DOI_RESOLVER_ADSABS_TOKEN` setting. Without a token
the `adsabs` resolver is skipped (it returns `None`), so DOI lookups
keep working and only bibcode lookups fail.

Because the ADS API returns JSON, no resolver deals with BibTeX anymore —
the `bibtexparser` dependency is gone entirely, consistent with the
habanero approach for Crossref.

## Installation

The plugin requires a working ColdFront deployment (tested against
ColdFront 1.1.x). It is not published on PyPI (yet); install it directly
from the
[GitHub repository](https://github.com/yoshson/coldfront-plugin-doi-resolver)
inside your ColdFront environment:

```console
$ uv pip install git+https://github.com/yoshson/coldfront-plugin-doi-resolver.git
```

Enable the plugin by creating `coldfront/config/plugins/doi_resolver.py`
in your ColdFront installation:

```python
from coldfront.config.base import INSTALLED_APPS

INSTALLED_APPS += [
    'coldfront_plugin_doi_resolver',
]
```

and register it in `coldfront/config/settings.py`:

```python
plugin_configs['PLUGIN_DOI_RESOLVER'] = 'plugins/doi_resolver.py'
```

Then set `PLUGIN_DOI_RESOLVER=True` in your environment (or local
settings). No migrations and no seeding commands are needed — the plugin
hooks into the publication search at application startup.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `DOI_RESOLVER_PATCH_PUBLICATION_SEARCH` | `True` | Automatically integrate with ColdFront: replace `PublicationSearchResultView._search_id` with the fixed resolver registry. Set to `False` if you want to wire things up yourself (mix `coldfront_plugin_doi_resolver.views.PublicationSearchResultMixin` into a custom view). |
| `DOI_RESOLVER_CROSSREF_MAILTO` | `None` | Contact address passed to Crossref so your requests use their "polite API" pool. |
| `DOI_RESOLVER_ADSABS_TOKEN` | `None` | Personal ADS API token ([get one here](https://ui.adsabs.harvard.edu/user/settings/token)) used as the `Authorization: Bearer` credential for bibcode lookups. Without it the `adsabs` resolver is skipped. |

## Adding a new registration agency

Add a decorated function to `resolvers.py` (or import the module and
decorate in another module that is imported at startup):

```python
@publication_resolver("my-ra.org", "https://my-ra.org/")
def resolve_my_ra(unique_id: str) -> dict | None:
    ...
    return {"author": ..., "year": ..., "title": ...,
            "journal": ..., "unique_id": unique_id}
```

The definition order is the lookup order; return `None` or raise on
failure (the view integration treats both as "not found via this RA" and
moves on).

## Development

```console
$ uv sync
$ uv run pytest
$ uv run ruff check
$ uv run ruff format --check
```

The resolvers are free of Django imports and covered by unit tests with
mocked HTTP responses (no network needed).

### Integration tests

The ColdFront integration is exercised against a **basic ColdFront test
instance** booted in-process: `tests/integration/settings.py` assembles the
settings from ColdFront's own config fragments, pytest-django creates and
migrates an in-memory SQLite database, and the tests drive the real
publication search view (with the resolver functions faked out). Run them
with the `integration` dependency group, which installs ColdFront 1.1.x:

```console
$ uv sync --group integration
$ uv run pytest tests/integration
```

Without the group, plain `uv run pytest` skips `tests/integration` at
collection time and runs only the resolver unit tests.

The repo root contains a minimal `manage.py` pointing at the test instance
settings (pytest-django needs it to locate the project). It also allows
exploring the instance by hand:

```console
$ uv run --group integration python manage.py check
$ DB_URL=sqlite:///coldfront.db uv run --group integration python manage.py migrate
```
