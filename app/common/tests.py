import subprocess

import pytest
from django.conf import settings


@pytest.mark.code
class TestCode:
    """
    Test if code passes pylint and black
    """

    def _check(self, args: list[str | int], error_message: str = None):
        """
        Run a check and raises and AssertionError if it fails.

        :param args: List of arguments composing the command to be executed
        :param error_message: Custom message when check fails. Defaults to CalledProcessError msg.
        """
        try:
            subprocess.run(args, check=True)
        except subprocess.CalledProcessError as exc:
            raise AssertionError(error_message or str(exc)) from exc

    def test_black(self):
        """
        Test if code passes black checks
        """
        self._check(
            ["black", "--check", settings.BASE_DIR / "app"],
            error_message="Black checks failed. Some code should be reformated.",
        )

    def test_pylint(self):
        """
        Test if code passes pylint checks
        """
        self._check(
            ["pylint", settings.BASE_DIR / "app"],
            error_message="Pylint checks failed. Some code contain errors.",
        )
