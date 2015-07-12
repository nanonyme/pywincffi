from textwrap import dedent
from os.path import dirname, join

try:
    from unittest.mock import Mock, patch
except ImportError:
    from mock import Mock, patch

from pywincffi.core.checks import Enums, input_check, error_check
from pywincffi.core.ffi import ffi
from pywincffi.core.testutil import TestCase
from pywincffi.exceptions import WindowsAPIError, InputError


class TestCheckErrorCode(TestCase):
    """
    Tests for :func:`pywincffi.core.ffi.check_error_code`
    """
    def test_default_code_does_match_expected(self):
        with patch.object(ffi, "getwinerror", return_value=(0, "GTG")):
            error_check("Foobar")

    def test_default_code_does_not_match_expected(self):
        with patch.object(ffi, "getwinerror", return_value=(0, "NGTG")):
            with self.assertRaises(WindowsAPIError):
                error_check("Foobar", expected=2)

    def test_non_zero(self):
        with patch.object(ffi, "getwinerror", return_value=(1, "NGTG")):
            error_check("Foobar", expected=Enums.NON_ZERO)

    def test_non_zero_success(self):
        with patch.object(ffi, "getwinerror", return_value=(0, "NGTG")):
            error_check("Foobar", code=1, expected=Enums.NON_ZERO)


class TestTypeCheck(TestCase):
    """
    Tests for :func:`pywincffi.core.types.input_check`
    """
    def test_type_error(self):
        with self.assertRaises(InputError):
            input_check("foobar", 1, str)

    def test_handle_type_failure(self):
        with self.assertRaises(InputError):
            input_check("", None, Enums.HANDLE)

    def test_not_a_handle(self):
        typeof = Mock(kind="", cname="")
        with patch.object(ffi, "typeof", return_value=typeof):
            with self.assertRaises(InputError):
                input_check("", None, Enums.HANDLE)

    def test_handle_type_success(self):
        typeof = Mock(kind="pointer", cname="void *")
        with patch.object(ffi, "typeof", return_value=typeof):
            # The value does not matter here since we're
            # mocking out typeof()
            input_check("", None, Enums.HANDLE)