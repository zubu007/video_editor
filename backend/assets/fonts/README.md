# Bundled caption fonts

Fonts burned into videos by the captions feature (`backend/features/captions/`).
Bundled so rendered output doesn't depend on the host's installed fonts; passed
to libass via the ffmpeg `ass` filter's `fontsdir` option.

All fonts are licensed under the SIL Open Font License 1.1 (see [OFL.txt](OFL.txt)):

| File | Family name | Source |
| --- | --- | --- |
| `Anton-Regular.ttf` | Anton | https://github.com/googlefonts/AntonFont |
| `Bangers-Regular.ttf` | Bangers | https://github.com/googlefonts/bangers |
| `Montserrat-ExtraBold.ttf` | Montserrat ExtraBold | https://github.com/JulietaUla/Montserrat |

When adding a font, register its exact family name (name-table ID 1) in
`FONT_FILES` in `backend/features/captions/styles.py` — libass matches by that
name and silently falls back to a default font on a mismatch.
