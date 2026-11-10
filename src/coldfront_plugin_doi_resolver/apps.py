"""Application configuration for the DOI resolver plugin."""

import logging

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class DoiResolverConfig(AppConfig):
    """Configure the plugin and hook it into ColdFront's publication search."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "coldfront_plugin_doi_resolver"
    label = "doi_resolver"
    verbose_name = "DOI Resolver"

    def ready(self):
        from django.conf import settings

        from coldfront_plugin_doi_resolver import resolvers

        # Optional contact address for Crossref's "polite API" pool.
        resolvers.CROSSREF_MAILTO = getattr(
            settings, "DOI_RESOLVER_CROSSREF_MAILTO", None
        )

        # Optional personal ADS API token for the adsabs (bibcode) resolver.
        resolvers.ADSABS_TOKEN = getattr(settings, "DOI_RESOLVER_ADSABS_TOKEN", None)

        # The automatic integration can be disabled, e.g. to combine the
        # mixin into a custom PublicationSearchResultView manually.
        if not getattr(settings, "DOI_RESOLVER_PATCH_PUBLICATION_SEARCH", True):
            logger.info(
                "DOI resolver plugin: automatic ColdFront integration "
                "disabled via DOI_RESOLVER_PATCH_PUBLICATION_SEARCH."
            )
            return

        try:
            from coldfront.core.publication import views as publication_views
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImproperlyConfigured(
                "coldfront_plugin_doi_resolver requires ColdFront to be "
                "installed and is meant to be used inside a ColdFront "
                "deployment. If you do not want the publication search to "
                "be patched, set DOI_RESOLVER_PATCH_PUBLICATION_SEARCH = "
                "False in your ColdFront settings."
            ) from exc

        from coldfront_plugin_doi_resolver.views import PublicationSearchResultMixin

        target = publication_views.PublicationSearchResultView
        if target._search_id is not PublicationSearchResultMixin._search_id:
            target._search_id = PublicationSearchResultMixin._search_id
            logger.info(
                "DOI resolver plugin: patched "
                "coldfront.core.publication.views.PublicationSearchResultView"
                " to use the fixed resolver registry."
            )
