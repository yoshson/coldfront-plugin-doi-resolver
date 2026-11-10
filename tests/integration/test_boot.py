"""The plugin boots inside a real ColdFront 1.1.x instance.

These tests run against a full ColdFront settings module (see
``settings.py``), so a passing ``django_db`` fixture already proves the
central integration step: ``AppConfig.ready()`` patches ColdFront's
``PublicationSearchResultView`` without breaking startup, and the
documented settings switches behave as advertised.
"""

import pytest
from coldfront.core.publication import views as publication_views
from django.apps import apps
from django.test import override_settings

from coldfront_plugin_doi_resolver import resolvers
from coldfront_plugin_doi_resolver.views import PublicationSearchResultMixin

pytestmark = pytest.mark.django_db


def test_patch_setting_disables_integration():
    """DOI_RESOLVER_PATCH_PUBLICATION_SEARCH=False leaves the view alone."""
    config = apps.get_app_config("doi_resolver")
    target = publication_views.PublicationSearchResultView

    def upstream_search_id(self, unique_id):
        return False

    original_search_id = target._search_id
    target._search_id = upstream_search_id
    try:
        with override_settings(DOI_RESOLVER_PATCH_PUBLICATION_SEARCH=False):
            config.ready()
        assert target._search_id is upstream_search_id
    finally:
        target._search_id = original_search_id
        # ready() is idempotent: it restores the patched view.
        config.ready()

    assert target._search_id is PublicationSearchResultMixin._search_id


def test_crossref_mailto_is_read_from_settings():
    """ready() propagates DOI_RESOLVER_CROSSREF_MAILTO to the resolvers."""
    config = apps.get_app_config("doi_resolver")
    original_mailto = resolvers.CROSSREF_MAILTO
    try:
        with override_settings(DOI_RESOLVER_CROSSREF_MAILTO="admin@example.org"):
            config.ready()
        assert resolvers.CROSSREF_MAILTO == "admin@example.org"
    finally:
        resolvers.CROSSREF_MAILTO = original_mailto
