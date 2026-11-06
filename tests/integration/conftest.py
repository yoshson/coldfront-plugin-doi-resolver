"""Fixtures for the ColdFront integration tests.

The database is created and migrated by pytest-django. A session fixture
then rounds it off into a *basic ColdFront instance*:

- ColdFront's status choices (``ProjectStatusChoice`` etc.) are not created
  by migrations but by its ``add_default_project_choices`` command,
- ColdFront's ``import_field_of_science_data`` command creates the NSF
  ``FieldOfScience`` rows, including the default row referenced by new
  projects.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


@pytest.fixture(scope="session", autouse=True)
def coldfront_test_instance(django_db_setup, django_db_blocker):
    """Set up the basic ColdFront test instance once per test session."""
    with django_db_blocker.unblock():
        call_command("add_default_project_choices")
        call_command("import_field_of_science_data")


@pytest.fixture
def pi_user(db):
    """A user who may own projects (ColdFront checks userprofile.is_pi)."""
    user = get_user_model().objects.create_user(
        username="test-pi", password="test-password"
    )
    user.userprofile.is_pi = True
    user.userprofile.save()
    return user


@pytest.fixture
def pi_client(client, pi_user):
    """A Django test client logged in as the PI."""
    client.force_login(pi_user)
    return client


@pytest.fixture
def project(db, pi_user):
    """An active project owned by the PI."""
    from coldfront.core.project.models import Project, ProjectStatusChoice

    return Project.objects.create(
        title="Test Project",
        pi=pi_user,
        status=ProjectStatusChoice.objects.get(name="Active"),
    )
