"""Verify timestamped proxy logs without running mitmproxy."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProxyLoggingTests(unittest.TestCase):
    def test_each_input_line_has_full_timestamp_and_port(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "lib/proxy-log.py"), "8087"],
            input=b"first event\nsecond event\n",
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.decode().splitlines()
        self.assertEqual(len(lines), 2)
        for line, value in zip(lines, ("first event", "second event"), strict=True):
            self.assertRegex(
                line,
                re.compile(
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}"
                    r"(?:[+-]\d{2}:\d{2}) \[mitmdump port=8087\] "
                ),
            )
            self.assertTrue(line.endswith(value))

    def test_invalid_utf8_is_replaced_in_log_instead_of_crashing(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "lib/proxy-log.py"), "8080"],
            input=b"\xff\n",
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("\ufffd", proc.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
