// Tests for QueuedMessagesStrip — the presentational strip above the composer
// listing messages queued while the agent is busy. It's a pure prop-driven
// component (no store access), so we exercise it with plain props.

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { QueuedMessage } from "@/store/chatStore";
import { QueuedMessagesStrip } from "./QueuedMessagesStrip";

const msg = (queueId: string, text: string): QueuedMessage => ({
  queueId,
  text,
  conversationId: "conv_abc",
});

i18n.addResources("en", "translation", {
  "chat.queue.reorder": "Reorder queued message",
  "chat.queue.sendNow": "Send queued message now",
  "chat.queue.steer": "Steer",
  "chat.queue.edit": "Edit queued message",
  "chat.queue.remove": "Remove queued message",
});
i18n.addResources("ru", "translation", {
  "chat.queue.reorder": "Изменить порядок сообщения в очереди",
  "chat.queue.sendNow": "Отправить сообщение из очереди сейчас",
  "chat.queue.steer": "Отправить сейчас",
  "chat.queue.edit": "Редактировать сообщение в очереди",
  "chat.queue.remove": "Удалить сообщение из очереди",
});

beforeEach(() => {
  void i18n.changeLanguage("en");
});
afterEach(cleanup);

describe("QueuedMessagesStrip", () => {
  it("renders nothing when the queue is empty", () => {
    const { container } = render(
      <QueuedMessagesStrip messages={[]} onDelete={vi.fn()} onEdit={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one row per queued message, in order", () => {
    render(
      <QueuedMessagesStrip
        messages={[msg("q_1", "first"), msg("q_2", "second")]}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();
  });

  it("calls onDelete with the row's queueId when its remove button is clicked", () => {
    const onDelete = vi.fn();
    render(
      <QueuedMessagesStrip
        messages={[msg("q_1", "first"), msg("q_2", "second")]}
        onDelete={onDelete}
        onEdit={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "Remove queued message" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]!);
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith("q_2");
  });

  it("calls onEdit with the row's queueId when its edit button is clicked", () => {
    const onEdit = vi.fn();
    render(
      <QueuedMessagesStrip
        messages={[msg("q_1", "first"), msg("q_2", "second")]}
        onDelete={vi.fn()}
        onEdit={onEdit}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "Edit queued message" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]!);
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit).toHaveBeenCalledWith("q_1");
  });

  it("shows no steer button when onSteer is omitted", () => {
    render(
      <QueuedMessagesStrip messages={[msg("q_1", "first")]} onDelete={vi.fn()} onEdit={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Send queued message now" })).toBeNull();
  });

  it("calls onSteer with the row's queueId when its steer button is clicked", () => {
    const onSteer = vi.fn();
    render(
      <QueuedMessagesStrip
        messages={[msg("q_1", "first"), msg("q_2", "second")]}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
        onSteer={onSteer}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "Send queued message now" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]!);
    expect(onSteer).toHaveBeenCalledTimes(1);
    expect(onSteer).toHaveBeenCalledWith("q_2");
  });

  it("localizes controls without translating queued message content", () => {
    render(
      <QueuedMessagesStrip
        messages={[msg("q_1", "Keep this user content")]}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
        onSteer={vi.fn()}
        onReorder={vi.fn()}
      />,
    );

    expect(screen.getByTestId("composer-queued-strip")).toBeInTheDocument();
    expect(screen.getByText("Keep this user content")).toBeInTheDocument();

    act(() => {
      void i18n.changeLanguage("ru");
    });

    expect(
      screen.getByRole("button", { name: "Изменить порядок сообщения в очереди" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Отправить сообщение из очереди сейчас" }),
    ).toHaveTextContent("Отправить сейчас");
    expect(
      screen.getByRole("button", { name: "Редактировать сообщение в очереди" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Удалить сообщение из очереди" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Keep this user content")).toBeInTheDocument();
  });

  it("shows a drag handle per row only when onReorder is provided", () => {
    const { rerender } = render(
      <QueuedMessagesStrip messages={[msg("q_1", "first")]} onDelete={vi.fn()} onEdit={vi.fn()} />,
    );
    // No reorder handler → no grip (the row shows the clock icon instead).
    expect(screen.queryByRole("button", { name: "Reorder queued message" })).toBeNull();

    rerender(
      <QueuedMessagesStrip
        messages={[msg("q_1", "first"), msg("q_2", "second")]}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
        onReorder={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Reorder queued message" })).toHaveLength(2);
  });
});
