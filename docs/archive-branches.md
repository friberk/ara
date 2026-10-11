# Archive branches

Merged feature branches are kept as a record of how the project was built, at the user's request. Every branch below is an ancestor of `main` (checked 2026-10-10). Don't delete, rebase or force-push them. When a new feature branch is merged, add it here.

| Round | Branch | Tip | Contents |
| --- | --- | --- | --- |
| Initial build | `feat/ai-research-assistant` | `526ef68` | The approved plan's core application (all five homework workflows). |
| Three features, merged at `5084b4f` | `feat/managed-ollama` | `6b53fd1` | Managed local models (ARA-022). |
| | `feat/fulltext-access` | `9fdd8c1` | Provider PDF access and retries (ARA-019). |
| | `feat/rag-context` | `e55a304` | Retrieval and context budgets (ARA-021, ARA-043). |
| | `integration-three-features` | `5084b4f` | Integration of the three branches above (ARA-082). |
| UI overhaul, fast-forwarded to `dd9a96d` | `feat/ui-overhaul` | `dd9a96d` | Chat-centred UI (ARA-033 to ARA-040). |
| | `feat/ui-api` | `524164c` | Agent branch. |
| | `feat/ui-content` | `2efd0f5` | Agent branch. |
| | `feat/ui-conversation` | `fe3cbf7` | Agent branch. |
| | `feat/ui-workspace` | `b1cbfc2` | Agent branch. |
| | `feat/ui-research` | `9d6843f` | Agent branch. |
| | `feat/ui-evidence` | `c48d71c` | Agent branch. |
| UX feedback round, merged at `a58154a` | `feat/ux-feedback-round` | `70d13ee` | Integration branch for ARA-083 to ARA-106. |
| | `feat/ara-083-chat-model` | `285f7f1` | |
| | `feat/ara-084-auto-pdf` | `c293074` | |
| | `feat/ara-085-context-meter` | `d534a52` | |
| | `feat/ara-086-upload-metadata` | `ad45b7a` | |
| | `feat/ara-087-openalex-pdf` | `52d5f5f` | |
| | `feat/ara-088-multi-paper-chats` | `e67aa42` | |
| | `feat/ara-089-citation-highlight` | `8822bbb` | |
| | `feat/ara-090-open-models-flag` | `2531874` | |
| | `feat/ara-091-library-embeddings` | `d7a941e` | |
| | `feat/ara-092-upload-match-tables` | `2e33784` | |
| | `feat/ara-093-hosted-catalog` | `ee81f23` | |
| | `feat/ara-094-evidence` | `91dd2b9` | |
| | `feat/ara-095-library-delete-edit` | `f36b4aa` | |
| | `feat/ara-096-mention-pills` | `9db1026` | |
| | `feat/ara-097-workspace-redesign` | `b352f44` | |
| | `feat/ara-098-pdf-state-icons` | `b8e120c` | |
| | `feat/ara-099-wordmark` | `612da2b` | |
| | `feat/ara-100-remove-activity` | `ae16321` | |
| | `feat/ara-101-paper-header` | `cd46f6d` | |
| | `feat/ara-101b-abstract-heading` | `135bd01` | |
| | `feat/ara-102-summary-card` | `1ae512a` | |
| | `feat/ara-103-sidebar-paper-actions` | `c620dde` | |
| | `feat/ara-104-chat-history` | `48acb1c` | |
| | `feat/ara-106-chat-polish` | `822c63a` | |
| Later merges | `feat/ara-105-section-summary-retry` | `eca4921` | Merged at `8ab9dd4`. |
| | `feat/ara-108-sidebar-theme` | `cbc334f` | Merged at `685703e`. |
| | `feat/ara-109-settings-dialog` | `c4556bb` | Settings dialog (ARA-109). |
| | `feat/ara-110-chat-paper-pills` | `3d6ff6e` | Chat paper pills (ARA-110). |
| | `feat/ara-110b-one-line-row` | `ab28046` | One-line paper row (ARA-110). |
| | `feat/ara-109c-library-copy` | `fb876bd` | Library and search copy, merged at `7045eda`. |
| | `feat/ara-113-demo-video` | `2f1b8f9` | Scripted demo video (ARA-113). |
| Retrieval agents, merged through `feat/rag-context` | `feat/rag-ingest` | `0c599ea` | Agent branch (ARA-071). |
| | `feat/rag-index` | `3d1f0dc` | Agent branch (ARA-072). |
| | `feat/rag-fixidx` | `a2041db` | Agent branch (ARA-072). |
| | `feat/rag-summary` | `22aab11` | Agent branch (ARA-073). |
| | `feat/rag-retrieval` | `69cd092` | Agent branch (ARA-074). |
| | `feat/rag-rerank` | `c93b8da` | Agent branch (ARA-074). |
| | `feat/rag-fixret` | `1650758` | Agent branch (ARA-074). |
| | `feat/rag-ui-a` | `689f6a7` | Agent branch (ARA-075). |
| | `feat/rag-context-budget` | `b22b853` | Agent branch (ARA-076). |
| | `feat/rag-memory` | `c7e7c2d` | Agent branch (ARA-077). |
| | `feat/rag-fixmem` | `4912672` | Agent branch (ARA-078). |
| | `feat/rag-ui-b` | `597cb1b` | Agent branch (ARA-078). |
| Other merged branches | `ara-019-fulltext` | `76dd5c6` | PDF retrieval plan (ARA-019). |
| | `docs/iteration-policy` | `c403662` | Iteration policy after the premature freeze (ARA-041). |
| | `feat/ara-107-deploy` | `a33bda7` | Demo deployment and CI deploy job (ARA-107). |
| | `feat/ara-107b-demo-access` | `e55a3fc` | Campus or demo-login access (ARA-107). |
| | `feat/ara-111-browser-specs` | `772fe88` | Browser specs after the UX round (ARA-111). |
| | `docs/ara-112-readme` | `cdaeedb` | README overhaul (ARA-112). |
| | `docs/ara-018-reflection-report` | `f8872a7` | Reflection report (ARA-018). |
| | `docs/ara-114-agents-md` | `cd1bd07` | AGENTS.md overhaul and the CLAUDE.md copy (ARA-114), merged at `7a71780`. |

Ignored local configuration and evidence from removed worktrees are kept under `docs/evidence/generated/worktree-archives/`.
