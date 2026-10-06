"""Tests for the immutable OverlayConfig value object."""

import pickle

import pytest

from image_metadata_overlay.config import DEFAULT_CONFIG, OverlayConfig


def test_defaults_match_expected():
    c = OverlayConfig()
    assert c.font_size == 128
    assert c.text_color == (255, 255, 255)
    assert c.target_epsg == 25832
    assert c.utm_zone == 32
    assert c.show_address is True


def test_immutable():
    with pytest.raises(Exception):  # FrozenInstanceError (a dataclasses FrozenInstanceError)
        DEFAULT_CONFIG.font_size = 999  # type: ignore[misc]


def test_with_overrides_returns_new_object():
    c2 = DEFAULT_CONFIG.with_overrides(font_size=72)
    assert c2.font_size == 72
    assert DEFAULT_CONFIG.font_size == 128  # original untouched


def test_to_from_dict_round_trip():
    c = DEFAULT_CONFIG.with_overrides(
        font_size=64, text_color=(1, 2, 3), project_info="Test", show_chainage=True
    )
    d = c.to_dict()
    # Keys are the legacy UPPERCASE format used by web settings / export JSON
    assert d["FONT_SIZE"] == 64
    assert d["TEXT_COLOR"] == (1, 2, 3)
    c2 = OverlayConfig.from_dict(d)
    assert c2 == c
    assert isinstance(c2.text_color, tuple)  # lists converted back to tuples


def test_from_dict_ignores_unknown_keys():
    c = OverlayConfig.from_dict({"FONT_SIZE": 90, "NO_SUCH_KEY": 1})
    assert c.font_size == 90


def test_pickleable_for_worker_processes():
    c = DEFAULT_CONFIG.with_overrides(font_size=55)
    assert pickle.loads(pickle.dumps(c)) == c


def test_validate_ok():
    assert DEFAULT_CONFIG.validate() is True


@pytest.mark.parametrize("field,value", [
    ("font_size", 0),
    ("font_size", 501),
    ("output_quality", 0),
    ("output_quality", 101),
    ("padding", -1),
    ("text_position", "middle"),
    ("file_collision_mode", "destroy"),
    ("target_epsg", 12),
    ("utm_zone", 0),
    ("utm_hemisphere", "X"),
    ("direction_precision", 4),
    ("text_color", (256, 0, 0)),
    ("text_color", (1, 2)),
    ("chainage_precision", 0),
])
def test_validate_rejects_invalid(field, value):
    with pytest.raises(ValueError):
        DEFAULT_CONFIG.with_overrides(**{field: value}).validate()
