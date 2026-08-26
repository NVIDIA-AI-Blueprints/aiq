# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral ontology tool roles."""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from nat.data_models.component_ref import FunctionRef


class OntologyProviderConfig(BaseModel):
    """Assign one ontology provider's tools to discovery and execution roles."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    catalog_tools: list[FunctionRef] = Field(min_length=1)
    execution_tools: list[FunctionRef] = Field(min_length=1)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize and reject blank provider identifiers."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("ontology provider identifier must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_tool_roles(self) -> "OntologyProviderConfig":
        """Reject duplicate or ambiguous role assignments."""

        catalog_names = [str(tool) for tool in self.catalog_tools]
        execution_names = [str(tool) for tool in self.execution_tools]
        if len(catalog_names) != len(set(catalog_names)):
            raise ValueError("ontology provider catalog_tools must not contain duplicates")
        if len(execution_names) != len(set(execution_names)):
            raise ValueError("ontology provider execution_tools must not contain duplicates")

        overlap = sorted(self.catalog_tool_names & self.execution_tool_names)
        if overlap:
            raise ValueError(f"ontology provider tool roles overlap: {', '.join(overlap)}")
        return self

    @property
    def catalog_tool_names(self) -> frozenset[str]:
        """Return exact catalog tool names."""

        return frozenset(str(tool) for tool in self.catalog_tools)

    @property
    def execution_tool_names(self) -> frozenset[str]:
        """Return exact execution tool names."""

        return frozenset(str(tool) for tool in self.execution_tools)

    @property
    def tool_names(self) -> frozenset[str]:
        """Return every assigned provider tool."""

        return self.catalog_tool_names | self.execution_tool_names


__all__ = ["OntologyProviderConfig"]
