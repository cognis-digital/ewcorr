"""Hardening tests — edge cases, bad input, and error-path coverage."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ewcorr import TOOL_NAME, TOOL_VERSION  # noqa: E402
from ewcorr.core import (  # noqa: E402
    CorrelationConfig,
    EmitterCluster,
    EWCorrError,
    parse_observations,
)
from ewcorr.cli import main  # noqa: E402


# ---------------------------------------------------------------------------
# Core / parse_observations
# ---------------------------------------------------------------------------

class TestParseEdgeCases(unittest.TestCase):
    def test_missing_required_column_raises(self):
        # Only has id + time — missing freq_mhz and bearing_deg.
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time\nA,0\n")
        self.assertIn("freq_mhz", str(ctx.exception))

    def test_empty_csv_header_only_raises(self):
        with self.assertRaises(EWCorrError):
            parse_observations("id,time,freq_mhz,bearing_deg\n")

    def test_blank_id_raises(self):
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time,freq_mhz,bearing_deg\n,0,100.0,45.0\n")
        self.assertIn("empty id", str(ctx.exception))

    def test_bad_freq_raises(self):
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time,freq_mhz,bearing_deg\nA,0,notanum,45.0\n")
        self.assertIn("freq_mhz", str(ctx.exception))

    def test_negative_freq_raises(self):
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time,freq_mhz,bearing_deg\nA,0,-1.0,45.0\n")
        self.assertIn("freq_mhz", str(ctx.exception))

    def test_bad_bearing_raises(self):
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time,freq_mhz,bearing_deg\nA,0,100.0,bad\n")
        self.assertIn("bearing_deg", str(ctx.exception))

    def test_bad_timestamp_raises(self):
        with self.assertRaises(EWCorrError) as ctx:
            parse_observations("id,time,freq_mhz,bearing_deg\nA,not-a-time,100.0,45.0\n")
        self.assertIn("timestamp", str(ctx.exception))

    def test_empty_string_raises(self):
        # Completely empty text — no header row at all.
        with self.assertRaises(EWCorrError):
            parse_observations("")

    def test_bearing_wrap_normalised(self):
        # 400 degrees should be normalised to 40.
        obs = parse_observations("id,time,freq_mhz,bearing_deg\nA,0,100.0,400.0\n")
        self.assertAlmostEqual(obs[0].bearing_deg, 40.0)


# ---------------------------------------------------------------------------
# EmitterCluster — empty-observations guard
# ---------------------------------------------------------------------------

class TestEmitterClusterEmpty(unittest.TestCase):
    """Properties on a cluster with no observations must raise EWCorrError."""

    def setUp(self):
        self.empty = EmitterCluster(emitter_id="EM-TEST", observations=[])

    def test_first_seen_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.first_seen

    def test_last_seen_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.last_seen

    def test_freq_center_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.freq_center_mhz

    def test_freq_span_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.freq_span_mhz

    def test_bearing_mean_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.bearing_mean_deg

    def test_bearing_spread_raises(self):
        with self.assertRaises(EWCorrError):
            _ = self.empty.bearing_spread_deg


# ---------------------------------------------------------------------------
# CorrelationConfig validation
# ---------------------------------------------------------------------------

class TestConfigValidation(unittest.TestCase):
    def test_zero_time_window_raises(self):
        with self.assertRaises(EWCorrError):
            CorrelationConfig(time_window_s=0.0).validate()

    def test_negative_time_window_raises(self):
        with self.assertRaises(EWCorrError):
            CorrelationConfig(time_window_s=-1.0).validate()

    def test_negative_freq_tol_raises(self):
        with self.assertRaises(EWCorrError):
            CorrelationConfig(freq_tol_mhz=-0.1).validate()

    def test_bearing_tol_over_180_raises(self):
        with self.assertRaises(EWCorrError):
            CorrelationConfig(bearing_tol_deg=181.0).validate()


# ---------------------------------------------------------------------------
# TOOL_NAME / TOOL_VERSION are now served from core (via VERSION file)
# ---------------------------------------------------------------------------

class TestToolIdentity(unittest.TestCase):
    def test_tool_name_is_ewcorr(self):
        self.assertEqual(TOOL_NAME, "ewcorr")

    def test_tool_version_matches_version_file(self):
        version_path = os.path.join(ROOT, "VERSION")
        with open(version_path, encoding="utf-8") as fh:
            expected = fh.read().strip()
        self.assertEqual(TOOL_VERSION, expected)


# ---------------------------------------------------------------------------
# CLI — new error paths
# ---------------------------------------------------------------------------

class TestCliHardeningPaths(unittest.TestCase):
    def test_missing_file_returns_2(self):
        rc = main(["correlate", os.path.join(ROOT, "no_such_file.csv")])
        self.assertEqual(rc, 2)

    def test_directory_as_file_returns_2(self):
        # Passing a directory instead of a file should exit 2, not crash.
        rc = main(["correlate", ROOT])
        self.assertEqual(rc, 2)

    def test_min_hits_zero_returns_2(self):
        demo = os.path.join(ROOT, "demos", "01-basic", "elint_log.csv")
        rc = main(["correlate", "--min-hits", "0", demo])
        self.assertEqual(rc, 2)

    def test_min_hits_negative_returns_2(self):
        demo = os.path.join(ROOT, "demos", "01-basic", "elint_log.csv")
        rc = main(["correlate", "--min-hits", "-1", demo])
        self.assertEqual(rc, 2)

    def test_malformed_csv_returns_2(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                        delete=False, encoding="utf-8") as tf:
            tf.write("col1,col2\n1,2\n3,4\n")
            bad_path = tf.name
        try:
            rc = main(["correlate", bad_path])
            self.assertEqual(rc, 2)
        finally:
            os.unlink(bad_path)

    def test_all_filtered_by_min_hits_returns_1(self):
        # All observations in a singleton log; min-hits=2 should give exit 1
        # (no emitters survived after filter — report["emitters"] == 0).
        text = "id,time,freq_mhz,bearing_deg\nA,0,100.0,45.0\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                        delete=False, encoding="utf-8") as tf:
            tf.write(text)
            path = tf.name
        try:
            rc = main(["correlate", "--min-hits", "2", path])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
