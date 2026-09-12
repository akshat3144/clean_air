"""The artifact contract.

These tests exist because the web app is built against this format before the
model produces real numbers. If the shape drifts, the front end breaks silently
and we find out late. So the shape is pinned here.

One test parses the TypeScript definitions to check both sides declare the same
fields. Crude, but it catches the failure that actually happens: someone adds a
field in Python and forgets the other side.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest

from cleanair.artifacts import fixtures, schema
from cleanair.artifacts.schema import Interval

TS_TYPES = Path(__file__).resolve().parents[1] / "web" / "src" / "types" / "artifacts.ts"


# --- Interval ---------------------------------------------------------------


def test_interval_rejects_unordered_bounds():
    with pytest.raises(ValueError, match="not ordered"):
        Interval(mean=0.05, lo=0.06, hi=0.07)


def test_interval_width_and_overlap():
    a = Interval(0.05, 0.04, 0.06)
    b = Interval(0.08, 0.07, 0.09)
    c = Interval(0.055, 0.045, 0.065)
    assert a.width == pytest.approx(0.02)
    assert not a.overlaps(b)
    assert a.overlaps(c)


# --- writing ----------------------------------------------------------------


def test_write_rejects_an_unknown_name(tmp_path):
    with pytest.raises(ValueError, match="unknown artifact"):
        schema.write("degredation", fixtures.degradation(), tmp_path)  # typo on purpose


def test_write_all_rejects_an_incomplete_bundle(tmp_path):
    partial = fixtures.bundle()
    del partial["power"]
    with pytest.raises(ValueError, match="missing"):
        schema.write_all(partial, tmp_path)


def test_write_all_produces_every_file(tmp_path):
    paths = schema.write_all(fixtures.bundle(), tmp_path)
    assert {p.stem for p in paths} == set(schema.FILES)
    for p in paths:
        json.loads(p.read_text(encoding="utf-8"))  # must be valid JSON


# --- fixture sanity ---------------------------------------------------------


def test_fixtures_are_flagged_as_not_real():
    """The app banners on this. If it were ever true for fixtures we could demo
    invented numbers by accident."""
    assert fixtures.meta().is_real is False


def test_degradation_keys_on_physical_compound_not_label():
    """The Step 1 finding: HARD/MEDIUM/SOFT are relative to each weekend's
    nomination, so grouping by them pools different rubber."""
    art = fixtures.degradation("practice")
    for curve in art.curves:
        assert curve.compound in ("C1", "C2", "C3", "C4", "C5")


def test_practice_and_race_are_separate_contexts():
    assert fixtures.degradation("practice").curves[0].context == "practice"
    assert fixtures.degradation("race").curves[0].context == "race"


def test_practice_fixture_has_the_physical_ordering():
    """Practice should show softer compounds degrading faster. The front end is
    built against these shapes, so a sign error here would mislead the design."""
    rates = {c.compound: c.rate.mean for c in fixtures.degradation("practice").curves}
    assert rates["C2"] < rates["C3"] < rates["C4"]


def test_race_fixture_reflects_the_collapse_we_measured():
    """In races the ordering does not hold — that is what the data showed, and
    the format has to be able to express it."""
    rates = {c.compound: c.rate.mean for c in fixtures.degradation("race").curves}
    assert not (rates["C2"] < rates["C3"] < rates["C4"])


def test_separation_values_are_probabilities():
    for v in fixtures.degradation("practice").separation.values():
        assert 0.0 <= v <= 1.0


def test_ablation_naive_band_is_wider_than_deconfounded():
    """The whole point of the money chart: deconfounding tightens the interval."""
    for row in fixtures.ablation().rows:
        assert row.naive.hi - row.naive.lo > row.deconfounded.hi - row.deconfounded.lo


def test_curve_is_monotonic_in_tyre_life():
    curve = fixtures.degradation("practice").curves[0].curve
    deltas = [p.delta.mean for p in curve]
    assert deltas == sorted(deltas), "an older tyre should never be faster"


def test_transfer_forecast_has_no_actuals():
    art = fixtures.transfer(forecast=True)
    assert art.is_forecast
    assert art.mae is None
    assert all(r.actual is None for r in art.rows)


# --- the two sides agree ----------------------------------------------------


def _ts_interface_fields(name: str) -> set[str]:
    src = TS_TYPES.read_text(encoding="utf-8")
    m = re.search(rf"export interface {name} \{{(.*?)\n\}}", src, re.S)
    assert m, f"interface {name} not found in artifacts.ts"
    body = re.sub(r"/\*.*?\*/|//.*", "", m.group(1), flags=re.S)
    return set(re.findall(r"^\s*(\w+)\??\s*:", body, re.M))


@pytest.mark.parametrize(
    "interface,obj",
    [
        ("Meta", fixtures.meta()),
        ("DegradationArtifact", fixtures.degradation()),
        ("AblationArtifact", fixtures.ablation()),
        ("BenchmarkArtifact", fixtures.benchmark()),
        ("CalibrationArtifact", fixtures.calibration()),
        ("PowerArtifact", fixtures.power()),
        ("TransferArtifact", fixtures.transfer()),
        ("StrategyArtifact", fixtures.strategy()),
        # Playbook was not covered here, so a field added to PlaybookEvent could
        # reach the app with no TypeScript counterpart. It is the biggest
        # artifact and the one the console reads, so it is the worst one to
        # leave unchecked.
        ("PlaybookArtifact", fixtures.playbook()),
        ("PlaybookEvent", fixtures.playbook().events[0]),
    ],
)
def test_typescript_declares_the_same_fields_as_python(interface, obj):
    assert _ts_interface_fields(interface) == set(asdict(obj))


def test_file_lists_match():
    src = TS_TYPES.read_text(encoding="utf-8")
    m = re.search(r"ARTIFACT_FILES = \[(.*?)\]", src, re.S)
    assert m
    assert tuple(re.findall(r'"(\w+)"', m.group(1))) == schema.FILES
