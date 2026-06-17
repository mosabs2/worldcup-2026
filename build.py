#!/usr/bin/env python3
"""Inline src/ modules into a single self-contained index.html."""
import datetime, pathlib, re, urllib.parse

# Machine-readable publish timestamp (UTC ISO-8601) for the on-site freshness
# badge: the page can show "updated N minutes ago" and flag a stale snapshot.
BUILT_AT = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SRC = pathlib.Path(__file__).parent / "src"
OUT = pathlib.Path(__file__).parent / "index.html"

shell = (SRC / "shell.html").read_text()
mono_w = (SRC / "assets" / "monogram-white.svg").read_text()
mono_b = (SRC / "assets" / "monogram-blue.svg").read_text()

def svg_body(svg):
    # strip XML prolog, keep the <svg> element, force full-size scaling
    svg = re.sub(r'<\?xml[^>]*\?>\s*', '', svg)
    svg = svg.replace('<svg ', '<svg width="100%" height="100%" ', 1)
    return svg.strip()

favicon = urllib.parse.quote(svg_body(mono_b).replace('\n', ' '))

html = (shell
    .replace("{{CSS}}", (SRC / "style.css").read_text())
    .replace("{{DATA}}", (SRC / "data.js").read_text())
    .replace("{{HISTORY}}", (SRC / "history.json").read_text())
    .replace("{{ESPNMAP}}", (SRC / "espn-map.json").read_text())
    .replace("{{MAP}}", (SRC / "map.json").read_text())
    .replace("{{ENGINE}}", (SRC / "engine.js").read_text())
    .replace("{{UI}}", (SRC / "ui.js").read_text())
    .replace("{{MONOGRAM_WHITE}}", svg_body(mono_w))
    .replace("{{MONOGRAM_BLUE}}", svg_body(mono_b))
    .replace("{{FAVICON}}", favicon)
    .replace("{{BUILT_AT}}", BUILT_AT))

assert not re.search(r"\{\{[A-Z_]+\}\}", html), "unresolved placeholder: " + str(re.findall(r"\{\{[A-Z_]+\}\}", html)[:3])
OUT.write_text(html)
print(f"built index.html ({len(html)//1024} KB)")
