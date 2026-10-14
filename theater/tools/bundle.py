"""Bundle the theater and some race files into one self-contained HTML page.

    python3 theater/tools/bundle.py out.html kikka2026 arima2025 february2026

Inlines course.js, engine.js and player.js (imports and exports stripped)
and the given theater/data/<name>.json files, with a race picker on top.
Handy for sharing one file; the multi-file version is theater/index.html.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def strip_module(src: str) -> str:
    src = re.sub(r"^import .*?;\n", "", src, flags=re.M)
    return re.sub(r"^export (?=(async )?(function|const|class|let))", "", src, flags=re.M)


def main():
    out, names = sys.argv[1], sys.argv[2:] or ["kikka2026"]
    races = {}
    for n in names:
        d = json.loads((ROOT / "data" / f"{n}.json").read_text(encoding="utf-8"))
        for h in d["horses"]:
            h.pop("recent", None)       # not shown by the player
        races[n] = d
    js = "\n".join(strip_module((ROOT / f).read_text(encoding="utf-8")) for f in ("course.js", "engine.js", "player.js"))
    options = "".join(f'<option value="{n}">{races[n]["title"]}</option>' for n in names)
    page = f"""<title>レース再現</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700&display=swap">
<style>
  :root{{--page:#eef1ec;--pick-ink:#18211c;--pick-rule:#d3dad3;--pick-bg:#ffffff}}
  @media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--page:#111714;--pick-ink:#e4ebe6;--pick-rule:#33413a;--pick-bg:#1e2722;color-scheme:dark}}}}
  :root[data-theme="dark"]{{--page:#111714;--pick-ink:#e4ebe6;--pick-rule:#33413a;--pick-bg:#1e2722;color-scheme:dark}}
  body{{background:var(--page);padding-block:12px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
  .pick{{max-width:1180px;margin:0 auto;display:flex;gap:8px;align-items:center;font:13px "BIZ UDPGothic",system-ui,sans-serif;color:var(--pick-ink)}}
  .pick select{{font:inherit;padding:3px 6px;border:1px solid var(--pick-rule);background:var(--pick-bg);color:var(--pick-ink)}}
</style>
<div class="pick"><label for="race">レース</label><select id="race">{options}</select></div>
<race-theater id="rt"></race-theater>
<script type="module">
const RACES = {json.dumps(races, ensure_ascii=False, separators=(",", ":"))};
const el = document.getElementById("rt");
el.field = RACES[{json.dumps(names[0])}];   // read when the element is defined below
{js}
document.getElementById("race").onchange = e => el.setField(RACES[e.target.value]);
</script>
"""
    Path(out).write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
