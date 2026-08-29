"""smart_discography_filter must tolerate null quality metadata.

Qobuz artist album lists sometimes carry null maximum_bit_depth /
maximum_sampling_rate (e.g. recent re-issues before quality scan).
The filter groups same-essence titles and max()es the quality fields —
None in the mix crashed with TypeError.
"""
import logging

from qdp.utils import smart_discography_filter

logging.disable(logging.CRITICAL)


def test_null_bit_depth_mixed_with_int_same_title():
    albums = [
        {"title": "A", "maximum_bit_depth": None, "maximum_sampling_rate": 44.1,
         "artist": {"name": "X"}},
        {"title": "A (2024 Remaster)", "maximum_bit_depth": 24,
         "maximum_sampling_rate": 96.0, "artist": {"name": "X"}},
    ]
    result = smart_discography_filter(albums)
    assert len(result) == 1
    assert result[0]["maximum_bit_depth"] == 24


def test_all_null_bit_depth_group():
    albums = [
        {"title": "B", "maximum_bit_depth": None, "maximum_sampling_rate": 44.1,
         "artist": {"name": "X"}},
        {"title": "B (Live)", "maximum_bit_depth": None,
         "maximum_sampling_rate": 96.0, "artist": {"name": "X"}},
    ]
    result = smart_discography_filter(albums)
    # both null: fall back to sampling-rate preference
    assert len(result) == 1
    assert result[0]["maximum_sampling_rate"] == 96.0


def test_null_sampling_rate_does_not_crash():
    albums = [
        {"title": "C", "maximum_bit_depth": 16, "maximum_sampling_rate": None,
         "artist": {"name": "X"}},
        {"title": "C (Deluxe)", "maximum_bit_depth": 24,
         "maximum_sampling_rate": 96.0, "artist": {"name": "X"}},
    ]
    result = smart_discography_filter(albums)
    assert len(result) == 1
    assert result[0]["maximum_bit_depth"] == 24


def test_missing_quality_keys_still_use_defaults():
    albums = [
        {"title": "D", "artist": {"name": "X"}},
        {"title": "D (Special)", "maximum_bit_depth": 24,
         "maximum_sampling_rate": 192.0, "artist": {"name": "X"}},
    ]
    result = smart_discography_filter(albums)
    assert len(result) == 1
    assert result[0]["maximum_bit_depth"] == 24


def test_save_space_prefers_lowest_rate():
    albums = [
        {"title": "E", "maximum_bit_depth": 24, "maximum_sampling_rate": 96.0,
         "artist": {"name": "X"}},
        {"title": "E (Rem)", "maximum_bit_depth": 24,
         "maximum_sampling_rate": 44.1, "artist": {"name": "X"}},
    ]
    result = smart_discography_filter(albums, save_space=True)
    assert len(result) == 1
    assert result[0]["maximum_sampling_rate"] == 44.1
