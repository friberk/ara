"""No test reaches a real external provider such as api.openai.com (ARA-074)."""

import httpx
import pytest
from openai import APIConnectionError, AsyncOpenAI


async def test_given_real_openai_url_when_requested_then_the_guard_refuses_it(no_external_network):
    client = AsyncOpenAI(api_key="fixture", base_url="https://api.openai.com/v1", max_retries=0)
    with pytest.raises(APIConnectionError):
        await client.post("/decisions", body={"model": "gpt-6-luna"}, cast_to=object)
    await client.close()
    assert no_external_network == ["https://api.openai.com/v1/decisions"]
    no_external_network.clear()  # Refusing this attempt is the point of the test.


async def test_given_any_external_host_when_requested_then_the_guard_refuses_it(
    no_external_network,
):
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://api.openalex.org/works")
    assert no_external_network == ["https://api.openalex.org/works"]
    no_external_network.clear()


async def test_given_in_process_transport_when_requested_then_the_guard_stays_out(
    no_external_network,
):
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.get("https://api.openai.com/v1/models")).status_code == 204
    assert no_external_network == []
