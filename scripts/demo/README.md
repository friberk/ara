# Demo video

These scripts record the homework demo video (ARA-113). They start an empty copy of ara beside your dev stack and drive it with [testreel](https://github.com/greentfrapp/testreel), which adds the cursor, the window frame and the background. The clips are then joined with black title cards that fade in and out.

Nothing here touches your dev data. The stack is a separate Compose project, `ara-demo`, with its own ports (5182 for the app, 8012 for the API) and its own volumes, and `stack.sh` refuses to manage any other project.

## What you need

- Docker with the app images built once, as for the dev stack.
- The root `.env` with the OpenAI and OpenAlex keys.
- Node 20 or newer. FFmpeg comes from `ffmpeg-static`, so you don't need a system copy.
- The two PDFs in `docs/evidence/generated/demo/inputs/` (Git ignores it):

```sh
mkdir -p docs/evidence/generated/demo/inputs
curl -fsSL -o docs/evidence/generated/demo/inputs/2406.11618v4.pdf https://arxiv.org/pdf/2406.11618v4
cp /path/to/usenixsecurity26-liu-yichen.pdf docs/evidence/generated/demo/inputs/
```

## Record

```sh
cd scripts/demo
npm ci
npx playwright install chromium   # once
npm test                          # timeline unit tests
node record.mjs --reset --run final
node assemble.mjs --run final
```

`--reset` empties the stack first, so every take starts with no papers, chats or search history. The recorder warms up the dev server, runs the nine clips in order and waits off camera between clips until background jobs finish. Clip 8 restarts the whole stack off camera before it shows the library again.

The video lands in `docs/evidence/generated/demo/<run>/ara-demo.mp4`. Each finished clip is also in `clips/`, and the cards are in `cards/`. Run `node cards.mjs` to preview the cards on their own.

A failed clip stops the run with a screenshot in `raw/`. `--only 05,06` re-records single clips into the same run, which works when the clip's starting state still holds. The summary, question and settings clips can be re-recorded this way. For anything else, take the whole run again with `--reset`, because uploading the same PDF twice opens the existing paper instead of preparing it.

When you're done, `./stack.sh down` stops the demo stack and keeps its data, and `./stack.sh reset` empties it.

## How the editing works

Waits for the network or the model are recorded in full and logged in `timeline.json`. `assemble.mjs` keeps the first few seconds after every new status label at normal speed, then speeds up the rest (at most 30×) and shows a "Sped up N×" badge in the window's title bar while it does. Streaming answers keep changing, so they play at normal speed. The rules live in `lib/timeline.mjs` and are covered by `lib/timeline.test.mjs`.
