# ara. branding

`ara-wordmark.svg`, `ara-mark.svg` and `favicon.svg` are outlines of "ara." in Instrument Serif Italic (OFL-1.1), shaped with HarfBuzz and tracked by `make_wordmark.py`. The frontend inlines the paths in `src/frontend/src/components/brand/AraBrand.tsx` and serves `favicon.svg` from `src/frontend/public/`.

## Regenerate

Font source: https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf

```sh
curl -L -o "$TMPDIR/InstrumentSerif-Italic.ttf" https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf
uv run --no-project --with fonttools==4.55.3 --with uharfbuzz==0.43.0 python -I branding/make_wordmark.py "$TMPDIR/InstrumentSerif-Italic.ttf" branding/
```

Do not commit the font file. After regenerating, update the inlined paths in `AraBrand.tsx` and copy `favicon.svg` to `src/frontend/public/favicon.svg` (`AraBrand.test.tsx` fails if the inlined paths differ from the SVGs, and `index-html.test.ts` checks the favicon copy).

## PNG fallbacks

`src/frontend/public/favicon-32.png` (32x32, light tile with rounded corners) and `apple-touch-icon.png` (180x180, opaque, square corners because iOS and Android apply their own mask) are rendered from `favicon.svg` with the frontend's Playwright Chromium. After `npm ci` in `src/frontend`, run `node branding/render_icons.mjs`. Commit the PNGs; no new dependencies.
