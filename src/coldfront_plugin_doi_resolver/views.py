"""View integration: replace upstream ``_search_id`` with the fixed registry.

ColdFront's ``PublicationSearchResultView`` decides which metadata sources
to try from the ``PublicationSource`` rows in its database and only knows
Crossref (via doi2bib) and ADS. The mixin below instead uses the fixed
registry from :mod:`coldfront_plugin_doi_resolver.resolvers`.
"""

import logging

from coldfront.core.publication.models import PublicationSource

from coldfront_plugin_doi_resolver.resolvers import get_registered_sources

logger = logging.getLogger(__name__)


class PublicationSearchResultMixin:
    """Drop-in mixin -- override ``_search_id`` to use the resolver registry.

    Iterates over the *fixed* registry of integrated registration agencies
    (in registration order). The first resolver that returns a non-``None``
    dict wins. The ``PublicationSource`` row matching the winning resolver
    is created on demand: upstream requires a source pk for the result
    formset and the final ``Publication.source`` foreign key, but which
    resolvers run must not depend on seeded database rows.
    """

    def _search_id(self, unique_id):
        for entry in get_registered_sources():
            try:
                pub_dict = entry.resolve(unique_id)
            except Exception:
                logger.info("Resolver %r failed for %r", entry.name, unique_id)
                continue

            if pub_dict:
                # The name is unique on PublicationSource; the url is only
                # a default for rows created here, so pre-existing rows
                # with a different url are reused as-is.
                source, _created = PublicationSource.objects.get_or_create(
                    name=entry.name, defaults={"url": entry.url}
                )
                pub_dict["source_pk"] = source.pk
                return pub_dict

        logger.error("All resolvers failed for %r", unique_id)
        return False
