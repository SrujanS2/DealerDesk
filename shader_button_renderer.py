import json
import re
from functools import lru_cache
from pathlib import Path


BUTTON_STUDIES_SOURCE = (
    Path(__file__).resolve().parent
    / "src"
    / "shaders"
    / "shader-buttons"
    / "sources"
    / "button-index.html"
)


@lru_cache(maxsize=8)
def get_iridescent_glass_html(
    mode: str = "dark",
    hue: float = 0,
    saturation: float = 1.0,
    brightness: float = 1.0,
) -> str:
    if mode not in {"dark", "light"}:
        raise ValueError("ShaderButtons mode must be 'dark' or 'light'.")
    if not BUTTON_STUDIES_SOURCE.is_file():
        raise FileNotFoundError(f"ThreeUI button source missing at: {BUTTON_STUDIES_SOURCE}")

    source = BUTTON_STUDIES_SOURCE.read_text(encoding="utf-8")
    download_status = "download:['Downloading…','Ready for Mac']"
    if source.count(download_status) != 1:
        raise ValueError("ThreeUI button source no longer has the expected action status.")
    source = source.replace(download_status, "download:['Searching…','Search ready']", 1)
    focus_styles = f"""<style data-threeui-study-focus>
    html, body, body > main, .button-list, .button-row[data-index="8"],
    .button-row[data-index="8"] .stage-frame,
    .button-row[data-index="8"] .stage {{ width: 100% !important; height: 100% !important; min-height: 0 !important; }}
    html, body {{ margin: 0 !important; padding: 0 !important; overflow: hidden !important; background: transparent !important; color-scheme: light !important; }}
    body > main {{ max-width: none !important; padding: 0 !important; }}
    .list-header, .list-footer, .button-row .number, .button-row .study-meta, .button-row .source {{ display: none !important; }}
    .button-list {{ display: block !important; margin: 0 !important; padding: 0 !important; list-style: none !important; }}
    .button-row {{ display: none !important; }}
    .button-row[data-index="8"] {{ display: block !important; border: 0 !important; padding: 0 !important; }}
    .button-row[data-index="8"] .stage-frame {{ display: block !important; overflow: hidden !important; }}
    .button-row[data-index="8"] .stage {{ display: block !important; overflow: hidden !important; }}
    .button-row[data-index="8"] .material-particles,
    .button-row[data-index="8"] .shader,
    .button-row[data-index="8"] .glass-download {{
      filter: hue-rotate({hue}deg) saturate({saturation}) brightness({brightness});
    }}
    .button-row[data-index="8"] .artboard {{
      top: calc(50% + 14px) !important;
      background: transparent !important;
      background-image: none !important;
      transform: translate(-50%, -50%) scale(var(--threeui-study-scale, 1)) !important;
      transition: none !important;
    }}
    .button-row[data-index="8"] .artboard::after,
    .button-row[data-index="8"] .ghost-ui {{ display: none !important; }}
    .button-row[data-index="8"] .stage[data-hover=true] .artboard,
    .button-row[data-index="8"] .stage[data-pressed=true] .artboard {{
      top: calc(50% + 14px) !important;
      background: transparent !important;
      background-image: none !important;
      transform: translate(-50%, -50%) scale(var(--threeui-study-scale, 1)) !important;
    }}
  </style>"""
    focus_script = f"""<script data-threeui-study-focus>
    (() => {{
      const index = 8;
      const mode = {json.dumps(mode)};
      document.querySelector('[data-theme-choice="' + mode + '"]')?.click();
      const stage = document.querySelector('#study-' + index);
      if (!stage) return;
      const label = stage.querySelector('button .label');
      if (label) label.textContent = 'Search';
      const fit = () => {{
        const scale = Math.min(innerWidth / 850, innerHeight / 650, 1.4);
        stage.style.setProperty('--threeui-study-scale', String(scale));
        stage.style.setProperty('--scale', String(scale));
      }};
      fit();
      addEventListener('resize', fit);
      document.querySelectorAll('.button-row').forEach(row => {{
        if (Number(row.dataset.index) === index) return;
        row.setAttribute('aria-hidden', 'true');
        row.inert = true;
      }});
      document.querySelector('.list-header')?.setAttribute('aria-hidden', 'true');
      document.querySelector('.list-footer')?.setAttribute('aria-hidden', 'true');
    }})();
  </script>"""

    source, head_count = re.subn(
        r"</head>",
        lambda match: f"{focus_styles}{match.group(0)}",
        source,
        count=1,
        flags=re.IGNORECASE,
    )
    source, body_count = re.subn(
        r"</body>",
        lambda match: f"{focus_script}{match.group(0)}",
        source,
        count=1,
        flags=re.IGNORECASE,
    )
    if head_count != 1 or body_count != 1:
        raise ValueError("ThreeUI button source is missing its expected document anchors.")
    return source
