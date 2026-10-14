import os

def get_semantic_bloom_html(text: str = "DealerDesk", mode: str = "dark", size: float = 1.0, opacity: float = 1.0) -> str:
    """
    Renders SemanticBloom using the exact canonical source and transformations
    defined in src/shaders/semantic-bloom/SemanticBloom.tsx
    """
    canonical_path = os.path.join(
        os.path.dirname(__file__),
        "src", "shaders", "semantic-bloom", "sources", "design-f0ebbe02-7d8a-41fd-9041-a1124185c27b.html"
    )

    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"Canonical source missing at: {canonical_path}")

    with open(canonical_path, "r", encoding="utf-8") as f:
        semantic_explorer_source = f.read()

    light = (mode == "light")
    surface = "transparent"
    resting_text = "#989894" if light else "#555555"
    active_text = "#151515" if light else "#e0e0e0"
    particle = "rgba(28, 28, 28, 0.78)" if light else "rgba(200, 200, 200, 0.8)"
    connection = "rgba(48, 48, 46, 0.14)" if light else "rgba(120, 120, 120, 0.15)"

    focus_styles = f"""<style data-semantic-bloom-focus>
:root {{
  --bg-color: {surface};
  --text-color: {resting_text};
  --highlight-color: {active_text};
  --sf-semantic-size: {size};
}}
html, body {{
  background: transparent !important;
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}}
.query-container, .status-hud, .noise-overlay {{ display: none !important; }}
.interface-layer {{
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
}}
.journal-area {{
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: auto;
  overflow: visible;
  color: {resting_text};
  font-size: clamp(3.2rem, calc(8vw * var(--sf-semantic-size)), 6.5rem);
  font-weight: 300;
  line-height: 1;
  letter-spacing: -0.065em;
  text-align: center;
  white-space: pre-wrap;
  caret-color: transparent;
  user-select: none;
}}
.journal-area .word {{ display: inline-block; color: {resting_text}; }}
#cursor-follower {{ display: none; border-color: {'rgba(0,0,0,0.28)' if light else 'rgba(255,255,255,0.3)'}; }}
@media (max-width: 640px) {{
  .interface-layer {{ padding: 1rem; }}
  .journal-area {{ font-size: clamp(2.4rem, calc(12vw * var(--sf-semantic-size)), 4.5rem); }}
}}
</style>"""

    safe_text = text.replace('"', '\\"').replace("'", "\\'")
    controls = f"""<script data-semantic-bloom-controls>
(function () {{
  window.__SEMANTIC_BLOOM_PAUSED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.__SEMANTIC_BLOOM_FRAME_PENDING = false;

  function setText(value) {{
    var next = typeof value === 'string' && value.trim() ? value.slice(0, 72) : '{safe_text}';
    if (!editor) return;
    editor.textContent = next;
    editor.dataset.processed = 'false';
    editor.setAttribute('contenteditable', 'false');
    scanText();
  }}

  window.addEventListener('message', function (event) {{
    if (!event.data || event.data.type !== 'semantic-bloom-controls') return;
    var next = event.data.controls || {{}};
    if (typeof next.text === 'string') setText(next.text);
    if (Number.isFinite(next.size)) {{
      document.documentElement.style.setProperty('--sf-semantic-size', String(Math.max(0.55, Math.min(1.6, next.size))));
      updateWordCoords();
    }}
    var wasPaused = window.__SEMANTIC_BLOOM_PAUSED;
    window.__SEMANTIC_BLOOM_PAUSED = Boolean(next.paused);
    if (wasPaused && !window.__SEMANTIC_BLOOM_PAUSED && !window.__SEMANTIC_BLOOM_FRAME_PENDING && typeof animate === 'function') animate();
  }});

  // Set initial text on startup matching configured usage
  window.addEventListener('DOMContentLoaded', function() {{
    setTimeout(function() {{ setText('{safe_text}'); }}, 60);
  }});
  setTimeout(function() {{ setText('{safe_text}'); }}, 120);
}})();
</script>"""

    slowed_motion_replacements = (
        (
            "this.angle += (Math.random() - 0.5) * 0.2;",
            "this.angle += (Math.random() - 0.5) * 0.15;",
        ),
        ("this.x += this.vx;", "this.x += this.vx * 0.75;"),
        ("this.y += this.vy;", "this.y += this.vy * 0.75;"),
    )
    for original, replacement in slowed_motion_replacements:
        if semantic_explorer_source.count(original) != 1:
            raise ValueError(f"Semantic Bloom source is missing expected motion code: {original}")
        semantic_explorer_source = semantic_explorer_source.replace(original, replacement, 1)

    rendered = (
        semantic_explorer_source
        .replace('<title vid="4">Organic Semantic Explorer</title>', '<title vid="4">Semantic Bloom</title>')
        .replace('</head>', f'{focus_styles}</head>')
        .replace("ctx.fillStyle = 'rgba(200, 200, 200, 0.8)';", f"ctx.fillStyle = '{particle}';")
        .replace("ctx.strokeStyle = 'rgba(120, 120, 120, 0.15)';", f"ctx.strokeStyle = '{connection}';")
        .replace(
            "function animate() {\n            \n            ctx.clearRect(0, 0, width, height);",
            "function animate() {\n            window.__SEMANTIC_BLOOM_FRAME_PENDING = false;\n            ctx.clearRect(0, 0, width, height);"
        )
        .replace(
            "requestAnimationFrame(animate);",
            "if (!window.__SEMANTIC_BLOOM_PAUSED) { window.__SEMANTIC_BLOOM_FRAME_PENDING = true; requestAnimationFrame(animate); }"
        )
        .replace('</body>', f'{controls}</body>')
    )

    return rendered
