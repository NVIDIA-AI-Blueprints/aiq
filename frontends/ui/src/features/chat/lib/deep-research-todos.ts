// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { DeepResearchTodo, DeepResearchTodoStatus } from '../types'

type RawDeepResearchTodo = {
  content: string
  status: string
}

const normalizeDeepResearchTodoStatus = (status: string): DeepResearchTodoStatus => {
  if (status === 'pending' || status === 'in_progress' || status === 'completed') {
    return status
  }
  if (status === 'stopped' || status === 'cancelled') {
    return 'stopped'
  }
  return 'pending'
}

export const normalizeDeepResearchTodos = (
  todos: RawDeepResearchTodo[]
): DeepResearchTodo[] => {
  return todos.map((todo, index) => ({
    id: `todo-${index}-${todo.content.substring(0, 20).replace(/\s+/g, '-').toLowerCase()}`,
    content: todo.content,
    status: normalizeDeepResearchTodoStatus(todo.status),
  }))
}
