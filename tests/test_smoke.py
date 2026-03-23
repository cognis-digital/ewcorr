"""Smoke tests for EWCORR. Standard library only, no network."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ewcorr import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    CorrelationConfig,
    correlate,
    parse_observations,
    summarize,
)
from ewcorr.core import EWCorrError, _circular_delta  # noqa: E402
from ewcorr.cli import main  # noqa: E402

DEMO = os.path.join(ROOT, "demos", "01-basic", "elint_log.csv")

SAMPLE = (
    "id,time,freq_mhz,bearing_deg,sensor\n"
    "A,0,9410.0,45.0,S1\n"
    "B,3,9410.1,45.2,S1\n"
    "C,5,2401.0,120.0,S2\n"
    "D,200,9410.0,45.0,S1\n"  # far in time -> separate emitter
)


class TestCore(unittest.TestCase):
    def test_metadata(self):
        self.assertEqual(TOOL_NAME, "ewcorr")
        self.assertTrue(TOOL_VERSION)

    def test_parse_and_correlate(self):
        obs = parse_observations(SAMPLE)
        self.assertEqual(len(obs), 4)
        clusters = correlate(obs, CorrelationConfig(time_window_s=30))
        # A+B link; C alone; D alone (out of time window) -> 3 clusters
        self.assertEqual(len(clusters), 3)
        sizes = sorted(c.count for c in clusters)
        self.assertEqual(sizes, [1, 1, 2])

    def test_circular_delta_wraparound(self):
        self.assertAlmostEqual(_circular_delta(359.0, 1.0), 2.0)
        self.assertAlmostEqual(_circular_delta(10.0, 350.0), 20.0)
        self.assertAlmostEqual(_circular_delta(0.0, 180.0), 180.0)

    def test_bearing_seam_clusters(self):
        # 359.5 and 0.6 should correlate as one emitter across the seam.
        text = (
            "id,time,freq_mhz,bearing_deg\n"
            "X,0,5610.0,359.5\n"
            "Y,2,5610.1,0.6\n"
        )
        clusters = correlate(parse_observations(text))
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].count, 2)

    def test_demo_file(self):
        with open(DEMO, encoding="utf-8") as fh:
            obs = parse_observations(fh.read())
        report = summarize(correlate(obs))
        self.assertEqual(report["observations"], 14)
        # 3 real emitters + 1 stray singleton
        self.assertEqual(report["emitters"], 4)
        self.assertEqual(report["singletons"], 1)

    def test_bad_input_raises(self):
        with self.assertRaises(EWCorrError):
            parse_observations("foo,bar\n1,2\n")
        with self.assertRaises(EWCorrError):
            parse_observations("id,time,freq_mhz,bearing_deg\n")

    def test_bad_config(self):
        with self.assertRaises(EWCorrError):
            correlate(parse_observations(SAMPLE), CorrelationConfig(time_window_s=0))


class TestCli(unittest.TestCase):
    def test_cli_json_success(self):
        rc = main(["--format", "json", "correlate", DEMO])
        self.assertEqual(rc, 0)

    def test_cli_min_hits_filters_singletons(self):
        rc = main(["correlate", "--min-hits", "2", DEMO])
        self.assertEqual(rc, 0)

    def test_cli_missing_file(self):
        rc = main(["correlate", os.path.join(ROOT, "does_not_exist.csv")])
        self.assertEqual(rc, 2)

    def test_subprocess_module_json(self):
        out = subprocess.run(
            [sys.executable, "-m", "ewcorr", "--format", "json", "correlate", DEMO],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        data = json.loads(out.stdout)
        self.assertEqual(data["observations"], 14)
        self.assertIn("clusters", data)

    def test_version(self):
        out = subprocess.run(
            [sys.executable, "-m", "ewcorr", "--version"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        self.assertIn(TOOL_VERSION, out.stdout)


if __name__ == "__main__":
    unittest.main()
