Optional: put your own font files here (.ttf or .otf) to use them on the slides.

1. Copy a bold and a regular font file into this folder, e.g. MyFont-Bold.ttf and MyFont-Regular.ttf.
2. In ../.env set:
     FONT_BOLD=/fonts/MyFont-Bold.ttf
     FONT_REG=/fonts/MyFont-Regular.ttf
3. Apply with:  docker compose up -d   then refresh the slides:
     docker compose exec updater python updater.py --once

If a font can't be loaded the updater logs a warning and uses the built-in DejaVu Sans.
Only use fonts you have the licence to use.
