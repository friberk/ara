"""Retrieval dependencies import offline; PDF libraries stay in the child parser (ARA-070)."""

import os
import subprocess
import sys


def test_retrieval_dependencies_import_without_network():
    code = (
        "import tiktoken, pgvector.sqlalchemy, llama_index.core, "
        "llama_index.embeddings.openai, llama_index.embeddings.ollama; "
        "[tiktoken.get_encoding(name) for name in ('o200k_base', 'cl100k_base')]"
    )
    # Any attempt to download tokenizer files fails through an unreachable proxy.
    env = {**os.environ, "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def test_parser_packages_are_pinned_together():
    from importlib.metadata import version

    assert version("pymupdf4llm") == "1.28.2"
    assert version("pymupdf") == "1.28.2"
    assert version("pymupdf_layout") == "1.28.2"


def test_application_modules_never_import_pdf_libraries():
    code = (
        "import importlib, pkgutil, sys, app\n"
        "skip = {'app.jobs.pdf_parser', 'app.jobs.actors', 'app.jobs.model_actors',"
        " 'app.jobs.development_worker'}\n"
        "for module in pkgutil.walk_packages(app.__path__, 'app.'):\n"
        "    if module.name not in skip:\n"
        "        importlib.import_module(module.name)\n"
        "loaded = sorted(name for name in sys.modules if name.split('.')[0] in"
        " {'pymupdf', 'pymupdf4llm', 'fitz'})\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
