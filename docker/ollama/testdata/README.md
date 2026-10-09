# IFM template fixture

`ara_ifm_chat_template.jinja` is the unmodified, complete `tokenizer.chat_template` extracted through `/api/show` from the retained `hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M` artifact. Its UTF-8 SHA-256 is `f6e3cd6dbf0f95016fff531f41f921dee541025733c14580a881cf5a5f9fa750`; it contains 43,040 bytes. The retained 3.7B artifact returned the identical template during a read-only metadata check. No 3.7B inference is part of this validation.

Artifact identity:

- Model origin: [IFM/K2-Horizon-7B-GGUF](https://huggingface.co/IFM/K2-Horizon-7B-GGUF).
- Retained weight SHA-256: `eb89c15a0ae9712be2ee462bf43802de14200f20f93b73da6eb68c2ebdd28e4e`.
- Retained Ollama manifest: `3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278`.
- License authority: [model card at repository revision 9fb01f7b397994455262f4b8256e4e00e4949ea9](https://huggingface.co/IFM/K2-Horizon-7B-GGUF/blob/9fb01f7b397994455262f4b8256e4e00e4949ea9/README.md), declaring Apache-2.0. The repository's current revision supplies license attribution; the retained artifact hashes above identify the bytes under test. A copy of the Apache-2.0 license is in `LICENSE.apache-2.0`.

The original model's [standalone template at revision 3b6ae394c1b863c27a306d168b25555837955192](https://huggingface.co/IFM/K2-Horizon-7B/blob/3b6ae394c1b863c27a306d168b25555837955192/chat_template.jinja) has a different hash (`a22d00a9622143643cd00af3ef80af10720c7793244060663b850b51e28b7fe8`). The runtime deliberately recognizes the retained GGUF template's exact bytes rather than granting controls to every template published for this family.

The fixture exercises real metadata discovery and native request validation. A one-byte template change must remove this local descriptor. Rendering and parser behavior are additionally checked against the real pinned llama.cpp server on the retained 7B weights. The fixture contains model template code only; it contains no uploaded paper or private interaction.
