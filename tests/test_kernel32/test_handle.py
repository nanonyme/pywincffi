import os
import shutil
import socket
import subprocess
import sys
import tempfile

from pywincffi.core import dist
from pywincffi.dev.testutil import TestCase
from pywincffi.kernel32 import (
    GetStdHandle, CloseHandle, GetHandleInformation,
    SetHandleInformation, DuplicateHandle, GetCurrentProcess, CreateEvent)
from pywincffi.wintypes import HANDLE, handle_from_file


class TestGetStdHandle(TestCase):
    """
    Tests for :func:`pywincffi.kernel32.GetStdHandle`
    """
    def test_stdin_handle(self):
        _, library = dist.load()
        self.assertEqual(
            GetStdHandle(library.STD_INPUT_HANDLE),
            HANDLE(library.GetStdHandle(library.STD_INPUT_HANDLE))
        )

    def test_stdout_handle(self):
        _, library = dist.load()
        self.assertEqual(
            GetStdHandle(library.STD_OUTPUT_HANDLE),
            HANDLE(library.GetStdHandle(library.STD_OUTPUT_HANDLE))
        )

    def test_stderr_handle(self):
        _, library = dist.load()
        self.assertEqual(
            GetStdHandle(library.STD_ERROR_HANDLE),
            HANDLE(library.GetStdHandle(library.STD_ERROR_HANDLE))
        )


class TestGetHandleInformation(TestCase):
    """
    Tests for :func:`pywincffi.kernel32.GetHandleInformation`
    """
    def test_get_handle_info_stdin(self):
        _, library = dist.load()
        stdin_handle = GetStdHandle(library.STD_INPUT_HANDLE)
        handle_flags = GetHandleInformation(stdin_handle)
        inherit = handle_flags & library.HANDLE_FLAG_INHERIT
        expected = (0, library.HANDLE_FLAG_INHERIT)
        self.assertIn(inherit, expected)

    def _expected_inheritance(self):
        # Python >= 3.4 creates non-inheritable handles (PEP 0446)
        _, library = dist.load()
        inherit = library.HANDLE_FLAG_INHERIT
        return inherit if sys.version_info[:2] < (3, 4) else 0

    def test_get_handle_info_file(self):
        _, library = dist.load()
        # can't use mkstemp: not inheritable on Python < 3.4
        tempdir = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, tempdir)
        filename = os.path.join(tempdir, "test_file")
        with open(filename, "w") as test_file:
            self.addCleanup(os.unlink, filename)
            test_file.write("data")
            file_handle = handle_from_file(test_file)
            handle_flags = GetHandleInformation(file_handle)
            inherit = handle_flags & library.HANDLE_FLAG_INHERIT
        expected = self._expected_inheritance()
        self.assertEqual(inherit, expected)

    def test_get_handle_info_socket(self):
        ffi, library = dist.load()
        sock = socket.socket()
        self.addCleanup(sock.close)
        sock_handle = HANDLE(ffi.cast("void *", sock.fileno()))
        handle_flags = GetHandleInformation(sock_handle)
        inherit = handle_flags & library.HANDLE_FLAG_INHERIT
        expected = self._expected_inheritance()
        self.assertEqual(inherit, expected)


class TestSetHandleInformation(TestCase):
    """
    Tests for :func:`pywincffi.kernel32.SetHandleInformation`
    """
    def _set_handle_info_file(self, inherit, check=False):
        _, library = dist.load()
        tempdir = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, tempdir)
        filename = os.path.join(tempdir, "test_file")
        with open(filename, "w") as test_file:
            self.addCleanup(os.unlink, filename)
            test_file.write("data")
            file_handle = handle_from_file(test_file)
            SetHandleInformation(
                file_handle,
                library.HANDLE_FLAG_INHERIT,
                inherit
            )
            if check:
                result = GetHandleInformation(file_handle)
                self.assertEqual(inherit, result)

    def test_set_handle_info_file_noinherit(self):
        self._set_handle_info_file(0)

    def test_set_handle_info_file_inherit(self):
        self._set_handle_info_file(1)

    def test_set_get_handle_info_file_noinherit(self):
        self._set_handle_info_file(0, check=True)

    def test_set_get_handle_info_file_inherit(self):
        self._set_handle_info_file(1, check=True)

    def _set_handle_info_socket(self, inherit, check=False):
        ffi, library = dist.load()
        sock = socket.socket()
        self.addCleanup(sock.close)
        sock_handle = HANDLE(ffi.cast("void *", sock.fileno()))
        SetHandleInformation(
            sock_handle,
            library.HANDLE_FLAG_INHERIT,
            inherit
        )
        if check:
            result = GetHandleInformation(sock_handle)
            self.assertEqual(inherit, result)

    def test_set_handle_info_socket_noinherit(self):
        self._set_handle_info_socket(0)

    def test_set_handle_info_socket_inherit(self):
        self._set_handle_info_socket(1)

    def test_set_get_handle_info_socket_noinherit(self):
        self._set_handle_info_socket(0, check=True)

    def test_set_get_handle_info_socket_inherit(self):
        self._set_handle_info_socket(1, check=True)


class TestSetHandleInformationChildSpawns(TestCase):
    """
    Integration tests for :func:`pywincffi.kernel32.SetHandleInformation`
    """
    def _spawn_child(self):
        return subprocess.Popen(
            args=[sys.executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

    def _cleanup_child(self, child):
        child.stdin.close()
        child.wait()

    def test_file_rename_after_spawn(self):
        _, library = dist.load()
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir, ignore_errors=True)
        filename = os.path.join(tempdir, "original_name")
        with open(filename, "w") as test_file:
            test_file.write("data")
            file_handle = handle_from_file(test_file)
            # prevent file_handle inheritance
            SetHandleInformation(file_handle, library.HANDLE_FLAG_INHERIT, 0)
            # spawn child while test_file is open
            child = self._spawn_child()
            self.addCleanup(self._cleanup_child, child)
        newfilename = os.path.join(tempdir, "new_name")
        # works as long as file is closed and not inherited by child
        os.rename(filename, newfilename)

    def test_socket_rebind_after_spawn(self):
        ffi, library = dist.load()
        bind_addr = (('127.0.0.1', 0))
        sock = socket.socket()
        try:
            sock.bind(bind_addr)
            bind_addr = sock.getsockname()
            sock_handle = HANDLE(ffi.cast("void *", sock.fileno()))
            # prevent file_handle inheritance
            SetHandleInformation(sock_handle, library.HANDLE_FLAG_INHERIT, 0)
            # spawn child while sock is bound
            child = self._spawn_child()
            self.addCleanup(self._cleanup_child, child)
        finally:
            sock.close()
        sock = socket.socket()
        self.addCleanup(sock.close)
        # re-bind to same address: works if not inherited by child
        sock.bind(bind_addr)


class TestDuplicateHandle(TestCase):
    """
    Integration tests for :func:`pywincffi.kernel32.DuplicateHandle`
    """
    def test_duplication(self):
        event = CreateEvent(False, False)
        self.addCleanup(CloseHandle, event)

        _, library = dist.load()
        handle = DuplicateHandle(
            GetCurrentProcess(),
            event,
            GetCurrentProcess(),
            0,
            True,
            library.DUPLICATE_SAME_ACCESS
        )
        self.addCleanup(CloseHandle, handle)
        info = GetHandleInformation(handle)
        self.assertEqual(info, library.HANDLE_FLAG_INHERIT)
