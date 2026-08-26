# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for tavily_web_fetch registration and adapter behavior."""

import asyncio
import os

from pydantic import SecretStr
from tavily_web_fetch.formatting import WRAP_WIDTH
from tavily_web_fetch.register import FetchUrlInput
from tavily_web_fetch.register import TavilyWebFetchToolConfig
from tavily_web_fetch.register import tavily_web_fetch

URL_A = "https://a.example/doc"
URL_B = "https://b.example/doc"


def extract_result(url, *, title="A title", raw_content="line one\nline two"):
    """Build one Tavily result entry."""
    return {"url": url, "title": title, "raw_content": raw_content, "images": []}


async def _call(config, fake, urls, **kwargs):
    """Register the tool and invoke it once."""
    async with tavily_web_fetch(config, None) as info:
        return await info.single_fn(FetchUrlInput(urls=urls, **kwargs))


class TestMissingKey:
    async def test_stub_returns_an_error_string_and_never_raises(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        async with tavily_web_fetch(TavilyWebFetchToolConfig(), None) as info:
            out = await info.single_fn(FetchUrlInput(urls=[URL_A]))
        assert out.startswith("Error:")
        assert "TAVILY_API_KEY" in out

    async def test_api_key_from_config_populates_the_environment(self, monkeypatch, fake_tavily):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A)]}
        config = TavilyWebFetchToolConfig(api_key=SecretStr("sk-from-config"))
        await _call(config, fake_tavily, [URL_A])
        assert os.environ.get("TAVILY_API_KEY") == "sk-from-config"


class TestInputValidation:
    async def test_keywords_instead_of_a_url_redirect_to_web_search_tool(self, fake_tavily):
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, ["maple syrup production by state"])
        assert out.startswith("Error:")
        assert "web_search_tool" in out
        fake_tavily.ainvoke.assert_not_awaited()

    async def test_non_http_schemes_are_rejected_without_a_request(self, fake_tavily):
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, ["file:///etc/passwd"])
        assert out.startswith("Error:")
        assert "http" in out
        fake_tavily.ainvoke.assert_not_awaited()

    async def test_empty_url_list_is_rejected(self, fake_tavily):
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [])
        assert out.startswith("Error:")
        assert "web_search_tool" in out

    async def test_too_many_urls_is_refused_with_the_limit(self, fake_tavily):
        config = TavilyWebFetchToolConfig(max_urls_per_call=2)
        out = await _call(config, fake_tavily, [URL_A, URL_B, "https://c.example/x"])
        assert out.startswith("Error:")
        assert "at most 2" in out
        fake_tavily.ainvoke.assert_not_awaited()


class TestTavilyAdapter:
    async def test_query_is_never_forwarded_to_tavily(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A)]}
        await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A], query="table 2.2")
        payload = fake_tavily.ainvoke.await_args.args[0]
        assert "query" not in payload
        assert payload["urls"] == [URL_A]

    async def test_attribute_error_from_langchain_becomes_a_clean_failure(self, fake_tavily):
        fake_tavily.ainvoke.side_effect = AttributeError("'str' object has no attribute 'get'")
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert out.startswith("Error:")
        assert "error response" in out

    async def test_error_payload_becomes_a_clean_failure(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"error": "bad request"}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert out.startswith("Error:")

    async def test_string_response_becomes_a_clean_failure(self, fake_tavily):
        fake_tavily.ainvoke.return_value = "some api error"
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert out.startswith("Error:")

    async def test_timeout_returns_a_message_and_never_raises(self, fake_tavily):
        async def _slow(_payload):
            await asyncio.sleep(5)

        fake_tavily.ainvoke.side_effect = _slow
        out = await _call(TavilyWebFetchToolConfig(timeout_seconds=1), fake_tavily, [URL_A])
        assert out.startswith("Error:")
        assert "did not respond" in out

    async def test_trailing_slash_differences_still_match_the_request(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A + "/")]}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert not out.startswith("Error:")
        assert 'status="ok"' in out

    async def test_case_sensitive_paths_remain_distinct(self, fake_tavily):
        uppercase_path = "https://a.example/Doc"
        lowercase_path = "https://a.example/doc"
        fake_tavily.ainvoke.return_value = {
            "results": [
                extract_result(uppercase_path, raw_content="uppercase page"),
                extract_result(lowercase_path, raw_content="lowercase page"),
            ]
        }

        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [uppercase_path, lowercase_path])

        assert out.count("uppercase page") == 1
        assert out.count("lowercase page") == 1


class TestResultShape:
    async def test_all_urls_failing_leads_with_error(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"results": []}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A, URL_B])
        assert out.startswith("Error:")

    async def test_partial_success_must_not_lead_with_error(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A)]}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A, URL_B])
        assert not out.startswith("Error:")
        assert 'status="ok"' in out
        assert 'status="failed"' in out

    async def test_soft_404_is_marked_suspect_and_cautioned(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {
            "results": [extract_result(URL_A, title="404", raw_content="Page not found. Sorry.")]
        }
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert 'status="suspect"' in out
        assert "Do not cite it" in out

    async def test_a_long_page_mentioning_not_found_is_not_flagged(self, fake_tavily):
        body = ("Discussion of HTTP semantics. " * 400) + " page not found "
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A, raw_content=body)]}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert 'status="ok"' in out

    async def test_per_call_budget_is_spent_in_request_order(self, fake_tavily):
        # The first page consumes the call budget, leaving the second below one wrapped line.
        fake_tavily.ainvoke.return_value = {
            "results": [
                extract_result(URL_A, raw_content="A " * 600),
                extract_result(URL_B, raw_content="B " * 600),
            ]
        }
        config = TavilyWebFetchToolConfig(max_chars_per_page=WRAP_WIDTH, max_chars_per_call=WRAP_WIDTH)
        out = await _call(config, fake_tavily, [URL_A, URL_B])
        assert 'status="skipped"' in out
        assert out.index(URL_A) < out.index(URL_B)

    async def test_sections_follow_the_requested_order(self, fake_tavily):
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_B), extract_result(URL_A)]}
        out = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A, URL_B])
        assert out.index(URL_A) < out.index(URL_B)


class TestRegistration:
    async def test_parser_registration_is_idempotent(self, fake_tavily, monkeypatch):
        calls = []
        from tavily_web_fetch import register as register_module

        from aiq_agent.common import citation_verification

        monkeypatch.setattr(register_module, "_parser_registered", False)
        monkeypatch.setattr(
            citation_verification, "register_source_parser", lambda matcher, parser: calls.append(parser)
        )
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A)]}
        for _ in range(3):
            await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])
        assert len(calls) == 1

    async def test_outbound_links_are_not_citable_under_any_instance_name(self, fake_tavily, monkeypatch):
        # The parser is registered before NAT applies the operator's YAML key, so it must key on
        # the output marker. Driving the real dispatcher is the only way to catch a name mismatch:
        # calling parse_fetched_pages directly hides it by hand-passing the name.
        from tavily_web_fetch import register as register_module

        from aiq_agent.common import citation_verification

        monkeypatch.setattr(citation_verification, "_PARSER_REGISTRY", [], raising=False)
        monkeypatch.setattr(register_module, "_parser_registered", False)

        body = "Real content.\nSee also https://outbound-never-fetched.example/page for more."
        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A, raw_content=body)]}
        rendered = await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])

        for instance_name in ("fetch_url_tool", "my_reader", "tavily_web_fetch"):
            sources = citation_verification.extract_sources_from_tool_result(instance_name, rendered)
            assert [entry.url for entry in sources] == [URL_A], instance_name

    async def test_other_tools_still_reach_the_generic_extractor(self, fake_tavily, monkeypatch):
        # The matcher accepts every name, so declining unfamiliar output is what keeps other tools
        # working.
        from tavily_web_fetch import register as register_module

        from aiq_agent.common import citation_verification

        monkeypatch.setattr(citation_verification, "_PARSER_REGISTRY", [], raising=False)
        monkeypatch.setattr(register_module, "_parser_registered", False)

        fake_tavily.ainvoke.return_value = {"results": [extract_result(URL_A)]}
        await _call(TavilyWebFetchToolConfig(), fake_tavily, [URL_A])

        sources = citation_verification.extract_sources_from_tool_result(
            "web_search_tool", "Result: https://x.example/1 and https://y.example/2"
        )
        assert [entry.url for entry in sources] == ["https://x.example/1", "https://y.example/2"]

    async def test_description_keeps_the_search_versus_fetch_contrast(self, fake_tavily):
        async with tavily_web_fetch(TavilyWebFetchToolConfig(), None) as info:
            description = info.description
        for literal in ("web_search_tool", "READER, not a FINDER", "DO NOT USE THIS TOOL WHEN", "exact URLs", "WRONG"):
            assert literal in description, f"missing from tool description: {literal!r}"

    async def test_input_schema_reaches_the_model_with_all_three_fields(self, fake_tavily):
        async with tavily_web_fetch(TavilyWebFetchToolConfig(), None) as info:
            fields = info.input_schema.model_fields
        assert set(fields) == {"urls", "query", "start_line"}
        assert "NOT search" in fields["urls"].description
        assert "does not search the web" in fields["query"].description
