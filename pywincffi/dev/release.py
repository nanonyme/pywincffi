"""
Release
=======

A module for developers which can retrieve information for or
produce a release.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from errno import EEXIST, ENOENT
from os.path import join, basename, dirname, abspath

try:
    from http.client import responses, OK
except ImportError:  # pragma: no cover
    # pylint: disable=import-error,wrong-import-order
    from httplib import responses, OK

import requests
from github import Github
from requests.adapters import HTTPAdapter

from pywincffi.core.config import config
from pywincffi.core.logger import get_logger

try:
    WindowsError
except NameError:  # pragma: no cover
    WindowsError = OSError  # pylint: disable=redefined-builtin

REPO_ROOT = dirname(dirname(dirname(abspath(__file__))))

logger = get_logger("dev.release")


def check_wheel(path):
    """
    Runs `wheel unpack` on ``path`` and returns True on success, False
    on failure.  This is used by :meth:`artifacts` to do some validation
    on the downloaded file.

    The intent of this method is to ensure that the file we downloaded
    structurally makes sense at a high level.  It's possible the file
    we downloaded could be corrupt or incomplete and we don't want to
    upload a bad file.

    :param str path:
        The path to run `wheel unpack` on.
    """
    unpack_dir = tempfile.mkdtemp()

    # Try to figure out where the wheel command is.  %PATH% itself
    # may not be setup correctly so we look in the most obvious places.
    wheel_commands = [
        "wheel",
        join(dirname(sys.executable), "Scripts", "wheel.exe"),
        join(dirname(sys.executable), "bin", "wheel"),
        join(dirname(sys.executable), "wheel.exe"),
        join(dirname(sys.executable), "wheel")

    ]
    for wheelcmd in wheel_commands:
        try:
            subprocess.check_call(
                [wheelcmd, "version"], stdout=subprocess.PIPE)
            break
        except (OSError, WindowsError) as error:  # pragma: no cover
            if error.errno == ENOENT:
                continue

            logger.error("Failed to execute %s", wheelcmd)
            raise
    else:  # pragma: no cover
        raise OSError(
            "Failed to locate the `wheel` command.  "
            "Searched %s." % wheel_commands)

    # pylint: disable=undefined-loop-variable
    command = [wheelcmd, "unpack", path, "--dest", unpack_dir]

    try:
        subprocess.check_call(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    except subprocess.CalledProcessError:
        logger.error("Failed to unpack wheel with %r", " ".join(command))
        return False

    else:
        shutil.rmtree(unpack_dir, ignore_errors=True)
        return True


class Session(object):
    """
    A class which acts as a provider for other APIs by sharing
    a single requests session
    Used by other APIs to construct and share a single
    :class:`requests.Session` as well
    """
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json"
    })

    @classmethod
    def check_code(cls, response, expected):
        """
        Check the HTTP response code from ``response`` against an
        expected value.

        :param requests.Response response:
            The response to check the status code for

        :param int expected:
            The expected http response code

        :raises RuntimeError:
            Raised if the response's HTTP status code does not
            match ``expected``
        """
        assert isinstance(response, requests.Response)

        if response.status_code != expected:
            raise RuntimeError(
                "Expected %s %s for GET %s. Got %s %s instead." % (
                    expected, responses[expected], response.url,
                    response.status_code, responses[response.status_code]))

    @classmethod
    def json(cls, url, expected=OK):
        """
        Downloads the requested url and returns the json data.

        :param str url:
            The url to request.

        :param int expected:
            The HTTP response code we should expect for 'success'.  This
            is set to 200 by default.

        :raises RuntimeError:
            Raised if the http response's status code does not
            equal ``expected``.
        """
        logger.debug("GET %s", url)
        response = cls.session.get(url)
        cls.check_code(response, expected)
        return response.json()

    @classmethod
    def download(cls, url, path=None, chunk_size=1024):
        """
        Downloads the data from ``url`` to the requested path or a
        random path if ``path`` is not provided

        :param str url:
            The url to download from

        :keyword str path:
            The path to download to.  A temporary file will be used
            if a path is not provided.

        :keyword int chunk_size:
            How large of a chunk to download at once from ``url``

        :return:
            Returns the path the data from ``url`` was written to.
        """
        if path is None:
            fd, path = tempfile.mkstemp()
            os.close(fd)

        logger.debug("GET %s -> %s", url, path)
        response = cls.session.get(url, stream=True)
        cls.check_code(response, OK)

        with open(path, "wb") as file_:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file_.write(chunk)

        return path


class GitHubAPI(object):
    """
    A wrapper around the :class:`github.GitHub` class
    which provides methods for constructing releases,
    tags, etc.
    """
    REPO_NAME = "opalmer/pywincffi"

    def __init__(self):
        github_token = config.get("pywincffi", "github_token")
        if not github_token:
            raise RuntimeError(
                "pywincffi.github_token is not set in the config")

        self.hub = Github(login_or_token=github_token)
        self.repo = self.hub.get_repo(self.REPO_NAME)

    def release_message(self, version):  # pylint: disable=no-self-use
        """Produces release message for :meth:`create_release` to use."""
        return version

    def create_release(self, version, recreate=False, prerelease=False):
        """
        Creates a release for requested version.

        :raises RuntimeError:
            Raised if a release for the given version already
            exists and ``recreate`` is False
        """
        for release in self.repo.get_releases():
            if release.tag_name == version:
                if recreate:
                    logger.warning(
                        "Deleting existing release for %s", release.tag_name)
                    release.delete_release()
                else:
                    raise RuntimeError(
                        "A release for %r already exists" % version)

        logger.info("Creating **draft** release %r", version)
        return self.repo.create_git_tag_and_release(
            tag=version,
            tag_message="Tagged by release.py",
            release_name=version,
            release_message=self.release_message(version),
            draft=True, prerelease=prerelease
        )


AppVeyorArtifact = namedtuple(
    "AppVeyorArtifact", ("path", "url", "unpacked", "build_success")
)


class AppVeyor(Session):
    """
    The core class used for interacting with and downloading content
    from AppVeyor.

    :keyword str branch:
        The branch to download and retrieve information for.  By default this
        is set to the 'master' branch.
    """
    API = "https://ci.appveyor.com/api"
    API_PROJECT = API + "/projects/opalmer/pywincffi"

    def __init__(self, branch="master"):
        self.session.mount(self.API, HTTPAdapter(max_retries=10))
        self.branch_name = branch
        self.branch = self.json(
            self.API_PROJECT + "/branch/%s" % self.branch_name)
        self.message = self.branch["build"]["message"]

    def artifacts(self, directory=None, ignore_failures=False):
        """
        Downloads the build artifacts to the requested directory.

        :keyword str directory:
            The directory to download the artifacts to.  By default a random
            directory will be created for you if one is not provided.

        :keyword bool ignore_failures:
            If True, only return the build artifacts if all jobs were
            successful.  This is False by default.

        :raises RuntimeError:
            Raised if there is a problem retrieving or validating one
            of the build artifacts.

        :rtype: iterator producing :class:`AppVeyorArtifact`
        """

        if directory is None:
            directory = tempfile.mkdtemp()

        logger.debug("Downloading build artifacts to %s", directory)

        try:
            os.makedirs(directory)
        except (OSError, IOError, WindowsError) as error:  # pragma: no cover
            if error.errno != EEXIST:
                raise

        for job in self.branch["build"]["jobs"]:
            job_id = job["jobId"]
            build_success = job["status"] == "success"

            if not ignore_failures and not build_success:
                raise RuntimeError(
                    "Cannot publish a failed job. "
                    "(%r != success)." % job["status"])

            # Iterate over and download all the artifacts
            artifact_url = \
                self.API + "/buildjobs/{id}/artifacts".format(id=job_id)

            build_artifacts = self.json(artifact_url)
            if not build_artifacts:
                logger.warning(
                    "Build %s does not contain any artifacts", artifact_url)

            for artifact in build_artifacts:
                if artifact["type"] != "File":  # pragma: no cover
                    logger.debug("Artifact %r is not a file.", artifact)
                    continue

                # Download the file.
                file_url = artifact_url + "/" + artifact["fileName"]
                logger.info("Download and unpack %s", file_url)
                local_path = join(directory, basename(artifact["fileName"]))
                self.download(file_url, path=local_path)

                unpacked = True
                if local_path.endswith(".whl"):
                    # Unpack the wheel to be sure the structure is correct.
                    # This helps to ensure that the download not incomplete
                    # or corrupt.  We don't really care about the resulting
                    # files.
                    unpacked = check_wheel(local_path)

                yield AppVeyorArtifact(
                    path=local_path, url=file_url,
                    unpacked=unpacked, build_success=build_success)
