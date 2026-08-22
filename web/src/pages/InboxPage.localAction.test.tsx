import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CommentInbox } from "@/hooks/useCommentInbox";
import type { Conversation } from "@/hooks/useConversations";
import * as commentInboxHook from "@/hooks/useCommentInbox";
import * as conversationsHook from "@/hooks/useConversations";
import * as sessionsApi from "@/lib/sessionsApi";
import i18n from "@/i18n";
import { InboxPage } from "./InboxPage";

vi.mock("@/hooks/useConversations", async (importActual) => ({
  ...(await importActual<typeof import("@/hooks/useConversations")>()),
  useConversations: vi.fn(),
}));
vi.mock("@/hooks/useCommentInbox", () => ({ useCommentInbox: vi.fn() }));
vi.mock("@/lib/sessionsApi", () => ({ getSession: vi.fn(), approve: vi.fn() }));

const row: Conversation = {
  id: "conv_local",
  object: "conversation",
  title: "Local action demo",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
  labels: {},
  permission_level: null,
  pending_elicitations_count: 1,
  archived: false,
};

function renderPage(localAction: Record<string, unknown>, rawMessage: string) {
  vi.mocked(sessionsApi.getSession).mockResolvedValue({
    pendingElicitations: [
      {
        type: "response.elicitation_request",
        elicitation_id: "elic_local",
        params: {
          mode: "form",
          message: rawMessage,
          requestedSchema: {},
          phase: "tool_call",
          policy_name: "local_runner",
          content_preview: rawMessage,
          local_action: localAction,
        },
      },
    ],
  } as unknown as Awaited<ReturnType<typeof sessionsApi.getSession>>);

  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  void i18n.changeLanguage("en");
  vi.mocked(conversationsHook.useConversations).mockReturnValue({
    data: { pages: [{ data: [row] }] },
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  } as unknown as ReturnType<typeof conversationsHook.useConversations>);
  vi.mocked(commentInboxHook.useCommentInbox).mockReturnValue({
    items: [],
    isLoading: false,
    failedCount: 0,
    retryFailed: vi.fn(),
  } satisfies CommentInbox);
  vi.mocked(sessionsApi.approve).mockResolvedValue(
    {} as Awaited<ReturnType<typeof sessionsApi.approve>>,
  );
});

afterEach(() => {
  cleanup();
  void i18n.changeLanguage("en");
  vi.clearAllMocks();
});

describe("InboxPage local-action approvals", () => {
  it("renders a sanitized typed shell card from a snapshot", async () => {
    const secret = "DEMO_TOKEN=not-a-real-secret";
    renderPage(
      {
        version: 1,
        kind: "run_shell",
        policy_mode: "manual",
        cwd: ".",
        path_summary: [],
        command_preview: "printf [arguments hidden]",
        diff_truncated: false,
        risk_flags: ["shell"],
        shell_guarantee: "trusted_machine",
      },
      `Approve local action containing ${secret}`,
    );

    expect(await screen.findByText("Run shell command")).toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText(/Trusted-machine shell/)).toBeInTheDocument();
    expect(screen.getByLabelText("Command preview")).toHaveTextContent("printf [arguments hidden]");
    expect(screen.queryByText(new RegExp(secret))).not.toBeInTheDocument();
  });

  it("renders a typed write card with its relative path and diff", async () => {
    renderPage(
      {
        version: 1,
        kind: "write_file",
        policy_mode: "manual",
        cwd: ".",
        path_summary: [".omnigent-demo-rejected.txt"],
        diff_preview: "--- /dev/null\n+++ .omnigent-demo-rejected.txt",
        diff_truncated: false,
        risk_flags: ["writes_files"],
      },
      "Approve local write",
    );

    expect(await screen.findByText("Write file")).toBeInTheDocument();
    expect(screen.getByText(".omnigent-demo-rejected.txt")).toBeInTheDocument();
    expect(screen.getByLabelText("Diff preview")).toHaveTextContent(
      "+++ .omnigent-demo-rejected.txt",
    );
  });
});
