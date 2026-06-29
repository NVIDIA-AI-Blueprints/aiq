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

"""Field-selection extensions for guardrails middleware."""

from __future__ import annotations

import types
import typing
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Sequence
from typing import Any
from typing import TypeAlias

from pydantic import BaseModel
from pydantic import Field
from pydantic import RootModel

FieldSelection: TypeAlias = list[str] | dict[str, list[str]]


class FunctionFieldSelection(RootModel[dict[str, FieldSelection]]):
    """Field selection for one dynamically intercepted function."""

    root: dict[str, FieldSelection] = Field(default_factory=dict)


class DynamicFieldSelectionConfigMixin(BaseModel):
    """Config extension for model-member field selections on dynamic middleware."""

    workflow_functions: list[str] | dict[str, FunctionFieldSelection] | None = Field(
        default=None,
        description="Workflow functions to wrap and optional field or model-member field selections.",
    )


class DynamicFieldSelectionMixin:
    """Traversal extension for dynamic middleware field selections."""

    def _path_resolves_to_string(self, schema: type[BaseModel], path: str) -> bool:
        """Return whether a dotted path resolves to a string-compatible leaf on a schema."""
        *prefix, last = path.split(".")
        current_schemas: list[type[BaseModel]] = [schema]

        for segment in prefix:
            next_schemas: list[type[BaseModel]] = []
            for current_schema in current_schemas:
                field: Any = current_schema.model_fields.get(segment)
                if field is None:
                    if current_schema.__name__ == segment:
                        next_schemas.append(current_schema)
                    continue

                resolved_schemas = self._annotation_model_choices(field.annotation)
                if not resolved_schemas:
                    return False
                next_schemas.extend(resolved_schemas)
            if not next_schemas:
                return False
            current_schemas = next_schemas

        return bool(current_schemas) and all(
            self._schema_field_is_string_compatible(current_schema, last) for current_schema in current_schemas
        )

    def _schema_field_is_string_compatible(self, schema: type[BaseModel], field_name: str) -> bool:
        """Return whether a schema field can provide string content to middleware."""
        field: Any = schema.model_fields.get(field_name)
        return field is not None and self._annotation_is_string_compatible(field.annotation)

    def _annotation_model_choices(self, annotation: Any) -> list[type[BaseModel]]:
        """Resolve every concrete model choice represented by an annotation."""
        annotation = self._strip_annotated(annotation)
        origin: Any = typing.get_origin(annotation)

        if origin in (typing.Union, types.UnionType):
            model_choices: list[type[BaseModel]] = []
            for arg in typing.get_args(annotation):
                if arg is type(None):
                    continue
                resolved = self._annotation_model_choices(arg)
                if not resolved:
                    return []
                model_choices.extend(resolved)
            return model_choices

        if origin in (list, tuple, set, frozenset, Sequence):
            element_args = typing.get_args(annotation)
            if not element_args:
                return []
            return self._annotation_model_choices(element_args[0])

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return [annotation]
        return []

    def _annotation_is_string_compatible(self, annotation: Any) -> bool:
        """Return whether an annotation can expose a string value at runtime."""
        annotation = self._strip_annotated(annotation)
        origin: Any = typing.get_origin(annotation)

        if annotation is str:
            return True
        if origin in (typing.Union, types.UnionType):
            return any(
                arg is not type(None) and self._annotation_is_string_compatible(arg)
                for arg in typing.get_args(annotation)
            )
        if origin in (list, tuple, set, frozenset, Sequence):
            element_args = typing.get_args(annotation)
            return bool(element_args) and self._annotation_is_string_compatible(element_args[0])
        return False

    def _strip_annotated(self, annotation: Any) -> Any:
        """Return the base annotation under any Annotated metadata."""
        while typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        return annotation

    def _resolve_guarded_targets(self, name: str) -> list[str]:
        """Expand configured field selections into traversal paths."""
        config = getattr(self, "_config", None) or getattr(self, "_guardrails_config", None)
        if config is None or not isinstance(config.workflow_functions, dict):
            return []

        selection: Any = config.workflow_functions.get(name)
        if selection is None:
            return []

        paths: list[str] = []
        for field, subpaths in selection.root.items():
            if isinstance(subpaths, dict):
                for model_name, model_subpaths in subpaths.items():
                    paths.extend(
                        [f"{field}.{model_name}"]
                        if not model_subpaths
                        else [f"{field}.{model_name}.{subpath}" for subpath in model_subpaths]
                    )
            else:
                paths.extend([field] if not subpaths else [f"{field}.{subpath}" for subpath in subpaths])
        return paths

    def _iter_targets_at_path(self, value: Any, path: str) -> Iterator[tuple[str, Callable[[str], None]]]:
        """Yield each string reached by a dotted path, including model-member selectors."""
        *prefix, last = path.split(".")
        parents: list[Any] = list(value) if isinstance(value, list) else [value]
        for segment in prefix:
            next_parents: list[Any] = []
            for node in parents:
                attr: Any = getattr(node, segment, None)
                if attr is not None:
                    next_parents.extend(attr if isinstance(attr, list) else [attr])
                elif node.__class__.__name__ == segment:
                    next_parents.append(node)
            parents = next_parents

        for parent in parents:
            leaf: Any = getattr(parent, last, None)
            if isinstance(leaf, str):
                yield leaf, self._set_modified_rail_value(parent, last)
            elif isinstance(leaf, list):
                for index, item in enumerate(leaf):
                    if isinstance(item, str):
                        yield item, self._set_modified_rail_value_in_list(leaf, index)
