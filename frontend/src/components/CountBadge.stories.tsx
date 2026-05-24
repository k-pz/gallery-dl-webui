import type { Meta, StoryObj } from "@storybook/react";
import { CountBadge } from "./CountBadge";

const meta: Meta<typeof CountBadge> = {
  component: CountBadge,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof CountBadge>;

export const Running: Story = { args: { running: 2, queued: 0 } };
export const Queued: Story = { args: { running: 0, queued: 3 } };
export const Mixed: Story = { args: { running: 1, queued: 5 } };
export const Empty: Story = { args: { running: 0, queued: 0 } };
