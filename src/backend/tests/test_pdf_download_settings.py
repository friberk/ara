import pytest

from app.core.config import Settings


def test_operator_hosts_are_exact_and_normalized():
    settings = Settings(fulltext_allowed_hosts=["ARXIV.ORG.", "aclanthology.org"], _env_file=None)
    assert settings.model_dump().get("fulltext_allowed_hosts") == ["arxiv.org", "aclanthology.org"]


@pytest.mark.parametrize(
    "host",
    ["*.example.org", "https://arxiv.org", "127.0.0.1", "user@arxiv.org", "", "arxiv.org:443"],
)
def test_operator_hosts_reject_wildcards_urls_and_private_literals(host):
    with pytest.raises(ValueError):
        Settings(fulltext_allowed_hosts=[host], _env_file=None)


async def test_resources_close_their_owned_downloader():
    from app.core.resources import Resources

    resources = Resources(Settings(_env_file=None))
    try:
        downloader = getattr(resources, "pdf_downloader", None)
        assert downloader is not None, "PDF clients must belong to the process/event loop"
    finally:
        await resources.close()
    assert downloader.client.is_closed
