// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * UI Adapters - KUI Component Re-exports
 *
 * This file re-exports KUI Foundations components for use in features.
 * Features should NEVER import directly from @nvidia/foundations-react-core.
 *
 * @example
 * ```tsx
 * // ✅ Correct - import from adapter
 * import { Button, Flex, Text } from '@/adapters/ui'
 *
 * // ❌ Wrong - direct import from package
 * import { Button } from '@nvidia/foundations-react-core'
 * ```
 */

// Layout Components
export { Flex, Stack, Grid, Block, Inline, Group, Divider } from '@nvidia/foundations-react-core'

// Typography
export { Text } from '@nvidia/foundations-react-core'

// Form Controls
export {
  Button,
  ButtonGroup,
  TextInput,
  TextArea,
  Select,
  Checkbox,
  RadioGroup,
  Switch,
  Slider,
  Upload,
  FormField,
  Combobox,
  DatePicker,
} from '@nvidia/foundations-react-core'

// Navigation
export {
  AppBar,
  VerticalNav,
  HorizontalNav,
  Breadcrumbs,
  Tabs,
  Pagination,
} from '@nvidia/foundations-react-core'

// Feedback
export {
  Spinner,
  ProgressBar,
  Skeleton,
  Toast,
  Notification,
  Banner,
  StatusIndicator,
  StatusMessage,
} from '@nvidia/foundations-react-core'

// Overlays
export {
  Modal,
  ModalCloseButton,
  Popover,
  Tooltip,
  SidePanel,
  Panel,
  Menu,
  Dropdown,
} from '@nvidia/foundations-react-core'

// Data Display
export { Card, Table, List, Avatar, Badge, Tag, Label, CodeSnippet } from '@nvidia/foundations-react-core'

// Utility Components
export {
  Accordion,
  Collapsible,
  Anchor,
  SegmentedControl,
  AnimatedChevron,
} from '@nvidia/foundations-react-core'

// Theme
export { ThemeProvider } from '@nvidia/foundations-react-core'

// Branding
// Logo is not available in @nvidia/foundations-react-core (public package).
// Re-exported from a local shim that renders the NVIDIA logo via CDN SVG.
export { Logo } from './Logo'

// Page Components
export { PageHeader, Hero } from '@nvidia/foundations-react-core'

// Type exports for component props (useful for extending)
export type {
  ButtonProps,
  TextProps,
  FlexProps,
  StackProps,
  CardProps,
  ModalProps,
  TooltipProps,
} from '@nvidia/foundations-react-core'
