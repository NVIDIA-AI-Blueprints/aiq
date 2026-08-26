// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Compose conditional class names with clsx and resolve conflicting Tailwind
 * utilities with tailwind-merge so later classes win deterministically.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
