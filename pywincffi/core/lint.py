"""
Lint Utilities
==============

Provides some help to pylint so static analysis can be
made aware of some constants and functions that we define
in headers.
"""

import re
from functools import partial
from os.path import dirname, abspath, join

try:
    from astroid import MANAGER, scoped_nodes

# The astroid is only needed by pylint.  We ignore ImportError
# here because the functions below are not called directory and
# we don't want this to be an extra dependency for the whole
# project.
except ImportError:
    pass

HEADERS_DIR = join(
    dirname(dirname(abspath(__file__))), "core", "cdefs", "headers")
SOURCES_DIR = join(
    dirname(dirname(abspath(__file__))), "core", "cdefs", "sources")
CONSTANTS_HEADER = join(HEADERS_DIR, "constants.h")
FUNCTIONS_HEADER = join(HEADERS_DIR, "functions.h")
SOURCE_MAIN = join(SOURCES_DIR, "main.c")
REGEX_FUNCTION = re.compile(r"^[A-Z]+ (.*)\(.*$")
REGEX_CONSTANT = re.compile(r"^#define ([A-Z]*[_]*[A-Z]*[_]*[A-Z]*) ...$")


def transform(cls, constants=None, functions=None):
    """
    Transforms class objects from pylint so they're aware of extra
    attributes that are not present when being statically analyzed.
    """
    assert isinstance(constants, set)
    assert isinstance(functions, set)

    for value in constants:
        cls.locals[value] = [scoped_nodes.Class(value, None)]

    for value in functions:
        cls.locals[value] = [scoped_nodes.Function(value, None)]


def register(linter):  # pylint: disable=unused-argument
    """
    An entrypoint that pylint uses to search for and register
    plugins with the given ``linter``
    """
    constants = set()
    functions = set()

    # Load constants from header
    with open(CONSTANTS_HEADER, "r") as constants_file:
        for line in constants_file:
            match = REGEX_CONSTANT.match(line)
            if match:
                constants.add(match.group(1))

    # Load functions from header
    with open(FUNCTIONS_HEADER, "r") as functions_file:
        for line in functions_file:
            match = REGEX_FUNCTION.match(line)
            if match:
                functions.add(match.group(1))

    # Load functions from source
    with open(SOURCE_MAIN, "r") as source_main_file:
        for line in source_main_file:
            match = REGEX_FUNCTION.match(line)
            if match:
                functions.add(match.group(1))

    # TODO: needs to change once we FFILibrary returns the prebuilt lib
    MANAGER.register_transform(
        scoped_nodes.Class,
        partial(transform, constants=constants, functions=functions),
        predicate=lambda node: node.name == "FFILibrary")