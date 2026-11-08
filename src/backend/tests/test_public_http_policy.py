"""PDFs are fetched only from allowed hosts on the scheme's default port (ARA-117)."""

import pytest

from app.integrations.public_http import DownloadPolicyError, PublicPDFTransport

HOST = "content.openalex.org"


def transport() -> PublicPDFTransport:
    return PublicPDFTransport([HOST])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://{HOST}/works/W1.pdf", (HOST, 443)),
        (f"https://{HOST}:443/works/W1.pdf", (HOST, 443)),
        (f"http://{HOST}/works/W1.pdf", (HOST, 80)),
        (f"http://{HOST}:80/works/W1.pdf", (HOST, 80)),
        ("https://CONTENT.OpenAlex.org./works/W1.pdf", (HOST, 443)),
    ],
)
def test_allowed_hosts_on_their_default_port_are_accepted(url, expected):
    assert transport().validate(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(f"https://{HOST}:8443/works/W1.pdf", id="https-other-port"),
        pytest.param(f"https://{HOST}:80/works/W1.pdf", id="https-on-http-port"),
        pytest.param(f"http://{HOST}:443/works/W1.pdf", id="http-on-https-port"),
        pytest.param(f"http://{HOST}:8080/works/W1.pdf", id="http-other-port"),
        pytest.param(f"https://{HOST}:99999/works/W1.pdf", id="port-out-of-range"),
        pytest.param(f"https://{HOST}:abc/works/W1.pdf", id="port-not-a-number"),
        pytest.param(f"ftp://{HOST}/works/W1.pdf", id="other-scheme"),
        pytest.param(f"https://user:secret@{HOST}/works/W1.pdf", id="credentials"),
        pytest.param("https://8.8.8.8/works/W1.pdf", id="ip-literal"),
        pytest.param("https://", id="no-host"),
        pytest.param(f"https://{HOST}/works/W1 .pdf", id="whitespace"),
        pytest.param(f"https://{HOST}/" + "a" * 4096, id="too-long"),
    ],
)
def test_unsafe_destinations_are_refused_before_any_lookup(url):
    with pytest.raises(DownloadPolicyError) as refused:
        transport().validate(url)
    assert refused.value.outcome == "unsafe_url"


def test_a_host_outside_the_allowed_set_is_refused_on_the_default_port():
    with pytest.raises(DownloadPolicyError) as refused:
        transport().validate("https://arxiv.org/pdf/1706.03762")
    assert refused.value.outcome == "unsafe_url"
