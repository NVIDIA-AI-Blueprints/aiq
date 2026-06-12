# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Tests for Polymarket search registration."""

from unittest.mock import MagicMock

from polymarket_prediction_market.register import PolymarketSearchToolConfig
from polymarket_prediction_market.register import _format_event_document
from polymarket_prediction_market.register import _format_market_document
from polymarket_prediction_market.register import polymarket_search

from nat.data_models.function import FunctionBaseConfig


class TestPolymarketSearchToolConfig:
    def test_defaults(self):
        config = PolymarketSearchToolConfig()

        assert config.max_results == 5
        assert config.active is True
        assert config.event_scan_limit == 100
        assert config.include_markets_per_event == 6
        assert config.timeout == 15.0
        assert config.max_retries == 2

    def test_inherits_from_function_base_config(self):
        assert issubclass(PolymarketSearchToolConfig, FunctionBaseConfig)


class TestPolymarketFormatting:
    def test_market_document_escapes_fields(self):
        output = _format_market_document(
            {
                "question": 'Will <script>alert("market")</script> win?',
                "url": 'https://polymarket.com/market?q=<script>&quote="yes"',
                "description": 'Market <description> & "details".',
                "outcomes": ["Yes <script>", 'No & "maybe"'],
                "outcomePrices": ["0.62", "0.38"],
                "endDate": '2026-11-03 <close> & "done"',
            }
        )

        assert "<script>" not in output
        assert "</script>" not in output
        assert 'href="https://polymarket.com/market?q=&lt;script&gt;&amp;quote=&quot;yes&quot;"' in output
        assert "Will &lt;script&gt;alert(&quot;market&quot;)&lt;/script&gt; win?" in output
        assert "Market &lt;description&gt; &amp; &quot;details&quot;." in output
        assert "Yes &lt;script&gt;: 62.0%" in output
        assert "No &amp; &quot;maybe&quot;: 38.0%" in output
        assert "<end_date>2026-11-03 &lt;close&gt; &amp; &quot;done&quot;</end_date>" in output

    def test_event_document_escapes_fields_and_nested_market_lines(self):
        output = _format_event_document(
            {
                "title": 'Election <event> & "odds"',
                "slug": 'election-<event>&"odds"',
                "description": 'Event <description> & "details".',
                "endDate": "2026-11-03 <close>",
                "markets": [
                    {
                        "question": 'Nested <market> & "line"',
                        "outcomes": ["Yes <win>", "No & lose"],
                        "outcomePrices": ["0.7", "0.3"],
                    }
                ],
            },
            max_markets=1,
        )

        assert "<event>" not in output
        assert "<market>" not in output
        assert 'href="https://polymarket.com/event/election-&lt;event&gt;&amp;&quot;odds&quot;"' in output
        assert "Election &lt;event&gt; &amp; &quot;odds&quot;" in output
        assert "Event &lt;description&gt; &amp; &quot;details&quot;." in output
        assert "<end_date>2026-11-03 &lt;close&gt;</end_date>" in output
        assert "Nested &lt;market&gt; &amp; &quot;line&quot;" in output
        assert "Yes &lt;win&gt;: 70.0%" in output
        assert "No &amp; lose: 30.0%" in output


class TestPolymarketSearchLive:
    async def test_successful_search_formats_event_and_market_documents(self, monkeypatch):
        calls = []

        async def fake_fetch_json(client, base_url, path, params):
            del client, base_url
            calls.append((path, params))
            if path == "/events":
                return [
                    {
                        "title": "Will Example win the 2026 election?",
                        "slug": "will-example-win-2026",
                        "description": "A market event about Example's election odds.",
                        "active": True,
                        "volume24hr": 12345,
                        "markets": [
                            {
                                "question": "Will Example win?",
                                "outcomes": '["Yes","No"]',
                                "outcomePrices": '["0.62","0.38"]',
                                "volume": "10000",
                                "liquidity": "5000",
                                "endDate": "2026-11-03T00:00:00Z",
                            }
                        ],
                    }
                ]
            return [
                {
                    "question": "Will Example win?",
                    "eventSlug": "will-example-win-2026",
                    "description": "Market level description.",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": ["0.62", "0.38"],
                    "active": True,
                }
            ]

        monkeypatch.setattr("polymarket_prediction_market.register._fetch_json", fake_fetch_json)

        config = PolymarketSearchToolConfig(max_results=2, include_markets_per_event=1)
        builder = MagicMock()
        async with polymarket_search(config, builder) as info:
            output = await info.single_fn("Example election odds")

        assert '<Document href="https://polymarket.com/event/will-example-win-2026">' in output
        assert "Will Example win the 2026 election?" in output
        assert "<source_type>prediction_market</source_type>" in output
        assert "Yes: 62.0%" in output
        assert "<volume>12.3K</volume>" in output
        assert calls[0][0] == "/events"
        assert calls[0][1]["active"] == "true"
        assert calls[1][0] == "/markets"
        assert calls[1][1]["keyword"] == "Example election odds"

    async def test_search_escapes_event_and_market_documents(self, monkeypatch):
        async def fake_fetch_json(client, base_url, path, params):
            del client, base_url, params
            if path == "/events":
                return [
                    {
                        "title": "Election <event> & odds",
                        "slug": "election-special-odds",
                        "description": "Event <description> & details",
                        "active": True,
                        "markets": [
                            {
                                "question": "Nested <market> & line",
                                "outcomes": ["Yes", "No"],
                                "outcomePrices": ["0.6", "0.4"],
                            }
                        ],
                    }
                ]
            return [
                {
                    "question": "Market <question> & election",
                    "url": "https://polymarket.com/market?name=<question>&side=yes",
                    "description": "Market <description> & details",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": ["0.55", "0.45"],
                    "active": True,
                }
            ]

        monkeypatch.setattr("polymarket_prediction_market.register._fetch_json", fake_fetch_json)

        config = PolymarketSearchToolConfig(max_results=2, include_markets_per_event=1)
        builder = MagicMock()
        async with polymarket_search(config, builder) as info:
            output = await info.single_fn("election market odds")

        assert "Election &lt;event&gt; &amp; odds" in output
        assert "Event &lt;description&gt; &amp; details" in output
        assert "Market &lt;question&gt; &amp; election" in output
        assert "Market &lt;description&gt; &amp; details" in output
        assert 'href="https://polymarket.com/market?name=&lt;question&gt;&amp;side=yes"' in output
        assert "<event>" not in output
        assert "<description>" not in output
        assert "<question>" not in output

    async def test_transient_fetch_error_retries_and_succeeds(self, monkeypatch):
        calls = []
        sleeps = []

        async def fake_fetch_json(client, base_url, path, params):
            del client, base_url, params
            calls.append(path)
            if len(calls) <= 2:
                raise ConnectionError("temporary outage")
            if path == "/events":
                return [
                    {
                        "title": "Retry market succeeds",
                        "slug": "retry-market-succeeds",
                        "description": "Retry path should return this event.",
                        "active": True,
                        "markets": [],
                    }
                ]
            return []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr("polymarket_prediction_market.register._fetch_json", fake_fetch_json)
        monkeypatch.setattr("polymarket_prediction_market.register.asyncio.sleep", fake_sleep)

        config = PolymarketSearchToolConfig(max_retries=2)
        builder = MagicMock()
        async with polymarket_search(config, builder) as info:
            output = await info.single_fn("retry market")

        assert "Retry market succeeds" in output
        assert calls == ["/events", "/markets", "/events", "/markets"]
        assert sleeps == [1]

    async def test_empty_query_returns_error_without_api_call(self, monkeypatch):
        async def fake_fetch_json(client, base_url, path, params):
            raise AssertionError("API should not be called")

        monkeypatch.setattr("polymarket_prediction_market.register._fetch_json", fake_fetch_json)

        config = PolymarketSearchToolConfig()
        builder = MagicMock()
        async with polymarket_search(config, builder) as info:
            output = await info.single_fn("  ")

        assert output == "Error: query must be a non-empty string"

    async def test_no_results_returns_clear_message(self, monkeypatch):
        async def fake_fetch_json(client, base_url, path, params):
            del client, base_url, path, params
            return []

        monkeypatch.setattr("polymarket_prediction_market.register._fetch_json", fake_fetch_json)

        config = PolymarketSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with polymarket_search(config, builder) as info:
            output = await info.single_fn("no matching market")

        assert output == "Polymarket search returned no results"
