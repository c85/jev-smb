import argparse

import pytest

from mario_jev.cli import parse_route


def test_parse_route_accepts_contiguous_levels():
    assert parse_route("1-1,1-2") == [(1, 1), (1, 2)]


@pytest.mark.parametrize("value", ["", "1", "1-5", "9-1", "one-two"])
def test_parse_route_rejects_invalid_levels(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_route(value)
