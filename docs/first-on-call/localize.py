"""Apply a translated strings.json to the offline lesson. Requires only Python 3.10+."""

import argparse
import json
import re
from collections import Counter
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "en-US"
TOKEN = re.compile(r"\{[a-zA-Z][a-zA-Z0-9_]*\}")


class LessonText(HTMLParser):
    """Locate keyed text in markup without parsing or rewriting scripts and styles."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.markup = markup
        self.lines = [0] + [m.end() for m in re.finditer("\n", markup)]
        self.strings = {}
        self.spans = []
        self.active = None
        self.feed(markup)
        self.close()
        if self.active:
            raise ValueError(f"Unclosed text element: {self.active[0]}")

    def source_position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if self.active:
            raise ValueError(f"Text key must contain plain text: {self.active[0]}")
        key = dict(attrs).get("data-key")
        if key is not None:
            if not key or key in self.strings:
                raise ValueError(f"Empty or duplicate text key: {key!r}")
            self.active = (key, tag, self.source_position() + len(self.get_starttag_text()))

    def handle_endtag(self, tag):
        if self.active is None:
            return
        key, expected_tag, begin = self.active
        if expected_tag != tag:
            raise ValueError(f"Unexpected closing tag for {key}")
        end = self.source_position()
        self.strings[key] = unescape(self.markup[begin:end])
        self.spans.append((begin, end, key))
        self.active = None

    def translated(self, strings):
        if not isinstance(strings, dict) or strings.keys() != self.strings.keys():
            raise ValueError("The translation must contain the same keys as the source catalog.")
        pieces = []
        position = 0
        for begin, end, key in self.spans:
            value = strings[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing text for {key}")
            if Counter(TOKEN.findall(value)) != Counter(TOKEN.findall(self.strings[key])):
                raise ValueError(f"Keep the named placeholders for {key}")
            pieces.extend((self.markup[position:begin], escape(value, quote=False)))
            position = end
        pieces.append(self.markup[position:])
        return "".join(pieces)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locale", nargs="?", help="Target language folder, for example ar or zh-Hans")
    parser.add_argument("--dir", choices=("ltr", "rtl"), default="ltr", help="Text direction")
    parser.add_argument("--page", choices=("index", "direction", "training", "readings"), default="index",
                        help="Lesson or standalone prediction exercise to translate")
    parser.add_argument("--force", action="store_true", help="Replace the selected target page")
    source_action = parser.add_mutually_exclusive_group()
    source_action.add_argument("--check", action="store_true", help="Check the US English catalog against the lesson")
    source_action.add_argument("--extract", action="store_true", help="Rebuild the US English catalog from its keyed lesson text")
    args = parser.parse_args()
    page_name = f"{args.page}.html"
    catalog_name = "strings.json" if args.page == "index" else f"{args.page}.strings.json"
    lesson = LessonText((SOURCE / page_name).read_text(encoding="utf-8"))
    if (args.extract or args.check) and args.locale:
        parser.error("Run source catalog commands without a target locale.")
    catalog_file = SOURCE / catalog_name
    if args.extract:
        english = {"locale": "en-US", "strings": lesson.strings}
        catalog_file.write_text(json.dumps(english, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    if catalog.get("locale") != "en-US" or catalog.get("strings") != lesson.strings:
        parser.error("The US English catalog and the lesson differ.")
    if args.check and not args.locale:
        print(f"Verified {len(lesson.strings)} US English lesson strings.")
        return
    if not args.locale or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", args.locale):
        parser.error("Use a language folder name such as ar, zh-Hans, or fr-CA.")
    if args.locale.casefold() == "en-us":
        parser.error("The US English source folder is reserved.")
    target = ROOT / args.locale
    try:
        data = json.loads((target / catalog_name).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("locale") != args.locale:
            raise ValueError("The catalog locale must match the folder name.")
        output = lesson.translated(data.get("strings"))
        source_tag = '<html lang="en-US" dir="ltr">'
        if output.count(source_tag) != 1:
            raise ValueError("The source HTML language tag has changed.")
        output = output.replace(source_tag, f'<html lang="{args.locale}" dir="{args.dir}">', 1)
        with (target / page_name).open("w" if args.force else "x", encoding="utf-8", newline="\n") as page:
            page.write(output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(target / page_name)


if __name__ == "__main__":
    main()
