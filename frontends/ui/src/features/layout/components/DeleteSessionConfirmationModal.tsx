// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DeleteSessionConfirmationModal Component
 *
 * Confirmation modal displayed before deleting a session.
 * Shows a warning message and requires explicit confirmation.
 */

'use client'

import { type FC } from 'react'
import { Modal, ModalCloseButton, Button, Flex, Text } from '@/adapters/ui'
import { Warning } from '@/adapters/ui/icons'

export interface DeleteSessionConfirmationModalProps {
  /** Whether the modal is open */
  open: boolean
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void
  /** Callback when delete is confirmed */
  onConfirm: () => void
}

/**
 * Modal for confirming session deletion.
 * Displays a warning message with Cancel and Delete Session actions.
 */
export const DeleteSessionConfirmationModal: FC<DeleteSessionConfirmationModalProps> = ({
  open,
  onOpenChange,
  onConfirm,
}) => {
  const handleConfirm = () => {
    onConfirm()
    onOpenChange(false)
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      slotHeading={
        <Flex align="center" gap="2">
          <Warning width={20} height={20} className="text-warning" />
          <span>Deleting Session</span>
        </Flex>
      }
      slotFooter={
        <>
          <ModalCloseButton kind="tertiary">Cancel</ModalCloseButton>
          <Button color="danger" onClick={handleConfirm}>
            Delete Session
          </Button>
        </>
      }
    >
      <Flex direction="col" gap="3">
        <Text kind="body/regular/md">
          You are about to delete this session. You will lose all progress and any files you have
          attached will be removed.
        </Text>
        <Text kind="body/regular/md">
          This action cannot be reversed. Are you sure you want to do this?
        </Text>
      </Flex>
    </Modal>
  )
}
