"""Regression tests for producing a portable translated lesson from its catalog."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LESSON = Path(__file__).resolve().parents[1] / "docs" / "first-on-call"


class LocalizationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy2(LESSON / "localize.py", self.root)
        shutil.copytree(LESSON / "en-US", self.root / "en-US")
        self.target = self.root / "ar"
        self.target.mkdir()
        self.catalog = json.loads((self.root / "en-US" / "strings.json").read_text(encoding="utf-8"))
        self.catalog["locale"] = "ar"

    def build(self):
        (self.target / "strings.json").write_text(json.dumps(self.catalog), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(self.root / "localize.py"), "ar", "--dir", "rtl"],
            capture_output=True, text=True, check=False,
        )

    def test_direction_unicode_escaping_and_overwrite_protection(self):
        self.catalog["strings"]["notes.empty"] = "اكتب <اسم> & احفظ"
        page = self.target / "index.html"
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = page.read_text(encoding="utf-8")
        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertIn("اكتب &lt;اسم&gt; &amp; احفظ", html)
        self.catalog["strings"]["notes.empty"] = "تغيير"
        self.assertNotEqual(self.build().returncode, 0)
        self.assertEqual(page.read_text(encoding="utf-8"), html)

    def test_missing_placeholders_and_keys_stop_generation(self):
        strings = self.catalog["strings"]
        key = next(key for key, value in strings.items() if "{" in value)
        strings[key] = "نص"
        self.assertIn("placeholders", self.build().stderr)
        del strings[key]
        self.assertIn("same keys", self.build().stderr)
        self.assertFalse((self.target / "index.html").exists())
