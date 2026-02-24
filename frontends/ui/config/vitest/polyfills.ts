// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { TextEncoder, TextDecoder } from 'util'

globalThis.TextEncoder = TextEncoder
globalThis.TextDecoder = TextDecoder as typeof globalThis.TextDecoder
