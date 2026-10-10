# ara. branding

`ara-wordmark.svg`, `ara-mark.svg` and `favicon.svg` are outlines of "ara." in Instrument Serif Italic (OFL-1.1), shaped with HarfBuzz and tracked by `make_wordmark.py`. The frontend inlines the paths in `src/frontend/src/components/brand/AraBrand.tsx` and serves `favicon.svg` from `src/frontend/public/`.

## Regenerate

Font source: https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf

```sh
curl -L -o "$TMPDIR/InstrumentSerif-Italic.ttf" https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf
uv run --no-project --with fonttools==4.55.3 --with uharfbuzz==0.43.0 python -I branding/make_wordmark.py "$TMPDIR/InstrumentSerif-Italic.ttf" branding/
```

Do not commit the font file. After regenerating, update the inlined paths in `AraBrand.tsx` and copy `favicon.svg` to `src/frontend/public/favicon.svg` (a test checks they match).
