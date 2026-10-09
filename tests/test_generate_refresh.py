"""generate.py refresh: a moved default arrives; a chosen value stays.

Runs under pytest, or on its own with no dependencies:

    python3 tests/test_generate_refresh.py

The case this exists for, from 2026-09-12: the template changed
tip_form_shear_temp from 150 to 0 and its comment to "OFF", the refresh kept
the 150 because it could not tell last version's default from a value someone
had chosen, and the printer ran shear mode under a comment saying it was off.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "installer"))
import generate  # noqa: E402

V1 = """[autoloader]
tip_form_shear_temp      : 150.0 # C - shear at this temperature
bowden_length_0          : 800.0 # mm - measured by SA_CALIBRATE_BOWDEN
feed_speed               : 50    # mm/s
"""

V2 = """[autoloader]
tip_form_shear_temp      : 0     # C - OFF
bowden_length_0          : 800.0 # mm - measured by SA_CALIBRATE_BOWDEN
feed_speed               : 60    # mm/s - raised in v2
"""


def _setting(text, key):
    for line in text.split("\n"):
        if line.startswith(key):
            return line
    raise AssertionError("no %s in output" % key)


def test_no_record_keeps_everything_as_before():
    # First refresh after this ships: no record, so a default and a choice
    # look the same and every differing value is kept, exactly as before.
    existing = {("autoloader", "tip_form_shear_temp"): "150.0",
                ("autoloader", "feed_speed"): "50"}
    text, changed, dropped, followed, moved = generate.reapply(V2, existing, None)
    assert "150.0" in _setting(text, "tip_form_shear_temp")
    assert followed == [] and moved == []


def test_untouched_default_follows_the_template():
    last = generate.template_defaults(V1)
    # The user never touched shear_temp: it is still v1's 150.0.
    existing = {("autoloader", "tip_form_shear_temp"): "150.0"}
    text, changed, dropped, followed, moved = generate.reapply(V2, existing, last)
    line = _setting(text, "tip_form_shear_temp")
    # Value AND comment from the new template, so they agree.
    assert ": 0" in line and "OFF" in line, line
    assert followed == [("autoloader", "tip_form_shear_temp", "150.0", "0")]
    assert moved == []


def test_chosen_value_stays_and_a_moved_default_is_reported():
    last = generate.template_defaults(V1)
    # The user raised feed_speed to 75; v2 moved the default from 50 to 60.
    existing = {("autoloader", "feed_speed"): "75"}
    text, changed, dropped, followed, moved = generate.reapply(V2, existing, last)
    assert ": 75" in _setting(text, "feed_speed")
    assert followed == []
    assert moved == [("autoloader", "feed_speed", "75", "50", "60")]


def test_chosen_value_with_an_unmoved_default_is_just_kept():
    last = generate.template_defaults(V1)
    # A measured bowden length: the template default did not move, so there
    # is nothing to say about it beyond keeping it.
    existing = {("autoloader", "bowden_length_0"): "1455.34"}
    text, changed, dropped, followed, moved = generate.reapply(V2, existing, last)
    assert "1455.34" in _setting(text, "bowden_length_0")
    assert followed == [] and moved == []
    assert changed == [("autoloader", "bowden_length_0", "800.0", "1455.34")]


def test_numbers_compare_as_numbers():
    # "150" on disk against "150.0" recorded is the same default.
    last = generate.template_defaults(V1)
    existing = {("autoloader", "tip_form_shear_temp"): "150"}
    _, _, _, followed, _ = generate.reapply(V2, existing, last)
    assert [f[1] for f in followed] == ["tip_form_shear_temp"]


def test_record_round_trips():
    d = tempfile.mkdtemp()
    table = {"parameters.cfg": generate.template_defaults(V1)}
    generate.save_defaults(d, table)
    assert generate.load_defaults(d) == table


def test_missing_or_corrupt_record_reads_as_none():
    d = tempfile.mkdtemp()
    assert generate.load_defaults(d) == {}
    with open(os.path.join(d, generate.DEFAULTS_FILE), "w") as f:
        f.write("{not json")
    assert generate.load_defaults(d) == {}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok   %s" % t.__name__)
    print("%d passed" % len(tests))
