from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).parents[1]
PUBLIC_DOCUMENTS = [
    ROOT / "README.md",
    ROOT / "docs" / "de" / "README.md",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "GITHUB_PRESENTATION.md",
]
DOCUMENTS = sorted(
    path
    for path in ROOT.rglob("*.md")
    if not any(part in {".git", ".venv", ".dev", ".test-runtime", "artifacts", "dist", "node_modules"} for part in path.parts)
)
BAD_ENCODING = ("\u0192", "\ufffd", "\u00c3", "\u00c2", "\u00e2")
PRIVATE_PATTERNS = (
    "cmeye",
    "e2e-owner",
    "e2e-only-disposable-password",
    "01kya",
    "127.0.0.1",
    "cmeyer",
)


class ImageAltParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.missing: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        values = dict(attrs)
        if not str(values.get("alt") or "").strip():
            self.missing.append(str(values.get("src") or "<unknown>"))


def local_target(raw: str, source: Path) -> Path | None:
    target = raw.strip().split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    return (source.parent / target).resolve()


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in range(0xC0, 0xC4):
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return width, height
        index += length
    raise ValueError(f"No JPEG dimensions found: {path}")


def main() -> int:
    errors: list[str] = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for character in BAD_ENCODING:
            if character in text:
                errors.append(f"encoding artifact {character!r} in {document.relative_to(ROOT)}")
        if document in PUBLIC_DOCUMENTS:
            for pattern in PRIVATE_PATTERNS:
                if pattern in text.lower():
                    errors.append(f"private pattern {pattern!r} in {document.relative_to(ROOT)}")

        parser = ImageAltParser()
        parser.feed(text)
        for image in parser.missing:
            errors.append(f"missing HTML image alt in {document.relative_to(ROOT)}: {image}")

        markdown_images = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text)
        for alt, target in markdown_images:
            if not alt.strip():
                errors.append(f"missing Markdown image alt in {document.relative_to(ROOT)}: {target}")
        targets = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)
        targets += [target for _, target in markdown_images]
        targets += re.findall(r"(?:src|srcset)=\"([^\"]+)\"", text)
        for target in targets:
            resolved = local_target(target, document)
            if resolved is not None and not resolved.exists():
                errors.append(f"broken local link in {document.relative_to(ROOT)}: {target}")

    social = ROOT / "docs" / "images" / "social-preview.jpg"
    if jpeg_dimensions(social) != (1280, 640):
        errors.append(f"social preview is {jpeg_dimensions(social)}, expected (1280, 640)")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Public documentation links, image alts, encoding, privacy markers, and social preview are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
