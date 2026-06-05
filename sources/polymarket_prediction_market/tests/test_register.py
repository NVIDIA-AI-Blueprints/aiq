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
