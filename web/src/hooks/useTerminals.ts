import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authenticatedFetch } from "../lib/identity";
import { useSessionRunnerOnline } from "@/hooks/RunnerHealthProvider";

/**
 * UI-facing terminal record.
 *
 * The wire response from ``GET /v1/sessions/{id}/resources/terminals``
 * is a richer ``session.resource``-shaped envelope; this struct lifts
 * the fields the UI actually renders and addresses (``id`` for
 * attach/close/tab keys, ``name``/``session`` for display).
 */
export interface TerminalInfo {
  /**
   * Opaque, stable resource id, e.g. ``"terminal_bash_s1"``. Used as
   * the addressing key for WS attach, close, and tab identity.
   */
  id: string;
  /** Terminal name from the spec, e.g. ``"bash"``. From ``metadata.terminal_name``. */
  name: string;
  /** Session key, e.g. ``"s1"``. From ``metadata.session_key``. */
  session: string;
  /** Whether the underlying tmux session is currently running. */
  running: boolean;
  /**
   * Web-attach transport for this terminal, from
   * ``metadata.terminal_transport``: ``"control"`` (tmux control mode —
   * native browser scrollback + selection) or ``"pty"`` (the legacy forked
   * ``tmux attach`` stream). ``undefined`` when the server omits it (older
   * server / treat as PTY).
   */
  transport?: "control" | "pty";
}

/**
 * Stable tab-id for a terminal, used as the Tabs trigger value.
 *
 * Keyed off the opaque resource id so the tab survives any future
 * display-field changes (rename, metadata churn). Format is
 * ``terminal:<id>``.
 */
export function terminalTabKey(t: TerminalInfo): string {
  return `terminal:${t.id}`;
}

/**
 * Sentinel passed to `openTerminalsPanel` / `onExpand` when the panel
 * should open in list-only view with no terminal pre-selected.
 * The AppShell treats any non-null key as "panel open"; TerminalsPanel
 * treats a falsy key as "no active terminal".
 */
export const PANEL_NO_TERMINAL_KEY = "";

/**
 * Resource ids of the AGENT's own terminal — the pane behind the
 * connection pill's Terminal view, runner-created per session shape:
 * the embedded Omnigent REPL (``tui``/``main``) for SDK sessions,
 * and the vendor pane (``claude``/``main``, ``codex``/``main``,
 * ``pi``/``main``, ``cursor``/``main``, ``kiro``/``main``, ``goose``/``main``,
 * ``qwen``/``main``, ``antigravity``/``main``, or ``kimi``/``main``) for
 * native-wrapper sessions.
 * These are plumbing, not part of the session's shell inventory, and at most
 * one exists per session.
 *
 * Missing an entry here makes that pane read as a *user shell*: the
 * Chat/Terminal pill self-hides in Terminal view (``isShellView``), so the
 * user is stranded in the terminal with no way back to Chat, and the pane
 * leaks into the Shells inventory.
 */
export const AGENT_TERMINAL_IDS: ReadonlySet<string> = new Set([
  "terminal_tui_main",
  "terminal_claude_main",
  "terminal_codex_main",
  "terminal_opencode_main",
  "terminal_pi_main",
  "terminal_cursor_main",
  "terminal_kiro_main",
  "terminal_goose_main",
  "terminal_qwen_main",
  "terminal_antigravity_main",
  "terminal_kimi_main",
  "terminal_hermes_main",
]);

/**
 * Whether *terminalKey* (a :func:`terminalTabKey` value) addresses the
 * agent's own terminal rather than a user shell.
 *
 * :param terminalKey: Tab key, e.g. ``"terminal:terminal_bash_s1"``.
 * :returns: ``true`` for the agent terminal of any session shape.
 */
export function isAgentTerminalKey(terminalKey: string): boolean {
  for (const id of AGENT_TERMINAL_IDS) {
    if (terminalKey === `terminal:${id}`) return true;
  }
  return false;
}

/**
 * Project the terminal list down to the session's *inventory* — the
 * shells shown in the right-rail Shells tab, its count badge, and the
 * mobile menu entry.
 *
 * For terminal-first sessions (SDK and native alike) the agent's own
 * terminal is excluded: it is reachable through the pill's Terminal
 * view, and listing it as a shell ("main · tui" / "main · claude")
 * reads as a phantom entry. The pill's own surfaces
 * (``terminalsAvailable``, MainTerminalView) keep the full list so
 * the agent terminal stays openable.
 */
export function inventoryTerminals(
  terminals: TerminalInfo[],
  isTerminalFirst: boolean,
): TerminalInfo[] {
  if (!isTerminalFirst) return terminals;
  return terminals.filter((t) => !AGENT_TERMINAL_IDS.has(t.id));
}

/**
 * TanStack Query key for a conversation's terminals.
 *
 * Exported so the chatStore SSE handler can target the same cache
 * entry when applying ``session.resource.{created,deleted}`` updates.
 *
 * :param conversationId: Session/conversation identifier.
 * :returns: Tuple identifying the cache entry.
 */
export function terminalsQueryKey(conversationId: string): readonly unknown[] {
  return ["conversation", conversationId, "terminals"];
}

interface UseTerminalsResult {
  terminals: TerminalInfo[];
  isLoading: boolean;
  error: Error | null;
}

/**
 * How often to retry terminal reconciliation during a bounded
 * bootstrap-recovery window.
 */
export const PENDING_RECONCILE_INTERVAL_MS = 2_500;

/**
 * Maximum number of consecutive non-authoritative terminal-list results.
 *
 * This count includes the initial request. With a 2.5-second interval,
 * four consecutive soft results allow three delayed retries before
 * polling stops.
 *
 * A later runner offline → online transition still performs a fresh
 * invalidation, so exhausting this local retry budget does not prevent
 * recovery after an actual runner restart.
 */
export const MAX_CONSECUTIVE_SOFT_TERMINAL_FETCHES = 4;

/**
 * Decide whether the terminals query needs temporary reconciliation polling.
 *
 * Poll in either of these recovery windows:
 *
 * 1. A terminal is being created while no terminal is visible.
 * 2. The runner reports online and the latest terminal-list request returned
 *    a soft, non-authoritative response, while the retry budget remains.
 */
export function terminalsReconcileInterval(
  reconcileWhilePending: boolean,
  terminalCount: number,
  runnerOnline: boolean | undefined = undefined,
  lastFetchAuthoritative: boolean | undefined = undefined,
  consecutiveSoftFetches = 0,
): number | false {
  if (reconcileWhilePending && terminalCount === 0) {
    return PENDING_RECONCILE_INTERVAL_MS;
  }

  if (
    runnerOnline === true &&
    lastFetchAuthoritative === false &&
    consecutiveSoftFetches < MAX_CONSECUTIVE_SOFT_TERMINAL_FETCHES
  ) {
    return PENDING_RECONCILE_INTERVAL_MS;
  }

  return false;
}

interface UseTerminalsOptions {
  /**
   * When ``true`` (the runner is auto-creating a terminal — see
   * ``terminalPending``), poll :func:`fetchTerminals` every
   * :data:`PENDING_RECONCILE_INTERVAL_MS` until a terminal appears.
   *
   * The query is otherwise fetch-once + live-SSE-delta driven. A single
   * missed ``session.resource.created`` delta (e.g. dropped through the
   * dbx-apps proxy before the SSE subscription opened, with the server's
   * best-effort snapshot-on-connect reconcile also timing out) would
   * otherwise leave ``terminals`` empty — stranding the Terminal-pill
   * spinner on ``terminalPending && !terminalsAvailable`` until a manual
   * page refresh. This bounded reconcile poll self-heals that exact
   * window: it stops the instant a terminal lands (or pending clears).
   */
  reconcileWhilePending?: boolean;
}

/**
 * Convert a single terminal-resource wire dict into the UI-facing
 * :class:`TerminalInfo`.
 *
 * The sole producer is the SSE-driven cache updater
 * (``applyTerminalCreated`` in the chatStore), which receives the
 * resource dict from ``session.resource.created`` events — both the
 * live deltas and the snapshot-on-connect replay.
 *
 * :param resource: Wire-shape resource dict from
 *     ``session.resource.created``. ``Record<string, unknown>`` to
 *     accommodate the SSE handler's permissive payload.
 * :returns: The mapped :class:`TerminalInfo`, or ``null`` when the
 *     resource lacks the minimum required fields.
 */
export function terminalInfoFromResource(resource: Record<string, unknown>): TerminalInfo | null {
  const id = resource.id;
  if (typeof id !== "string" || !id) return null;
  const rawMetadata = resource.metadata;
  const metadata =
    rawMetadata && typeof rawMetadata === "object" && !Array.isArray(rawMetadata)
      ? (rawMetadata as Record<string, unknown>)
      : {};
  const terminalName = metadata.terminal_name;
  const sessionKey = metadata.session_key;
  const running = metadata.running;
  const rawTransport = metadata.terminal_transport;
  const transport = rawTransport === "control" || rawTransport === "pty" ? rawTransport : undefined;
  const fallbackName = resource.name;
  return {
    id,
    // metadata.terminal_name / metadata.session_key are the canonical
    // wire location for these display fields under the resources API.
    // Fall back to the resource ``name`` for terminal_name so a server
    // that omits metadata still renders something recognizable; empty
    // string for session is acceptable because the UI dedupes by id.
    name:
      typeof terminalName === "string" && terminalName
        ? terminalName
        : typeof fallbackName === "string"
          ? fallbackName
          : "",
    session: typeof sessionKey === "string" ? sessionKey : "",
    running: typeof running === "boolean" ? running : false,
    transport,
  };
}

const _SOFT_TERMINAL_LIST_STATUSES = new Set([404, 409, 502, 503]);

const terminalSnapshotKey = (conversationId: string) => `omnigent.terminals.${conversationId}`;

function isTerminalInfo(value: unknown): value is TerminalInfo {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const terminal = value as Record<string, unknown>;
  return (
    typeof terminal.id === "string" &&
    terminal.id.length > 0 &&
    typeof terminal.name === "string" &&
    typeof terminal.session === "string" &&
    typeof terminal.running === "boolean" &&
    (terminal.transport === undefined ||
      terminal.transport === "control" ||
      terminal.transport === "pty")
  );
}

export function readStoredTerminals(conversationId: string): TerminalInfo[] {
  try {
    const raw = sessionStorage.getItem(terminalSnapshotKey(conversationId));
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    const terminals: TerminalInfo[] = [];
    const seenIds = new Set<string>();

    for (const candidate of parsed) {
      if (!isTerminalInfo(candidate)) continue;
      if (seenIds.has(candidate.id)) continue;
      seenIds.add(candidate.id);
      terminals.push(candidate);
    }

    return terminals;
  } catch {
    return [];
  }
}

export function writeStoredTerminals(conversationId: string, terminals: TerminalInfo[]): void {
  try {
    sessionStorage.setItem(terminalSnapshotKey(conversationId), JSON.stringify(terminals));
  } catch {
    // Persistence is best-effort when browser storage is unavailable.
  }
}

interface TerminalFetchResult {
  terminals: TerminalInfo[];
  authoritative: boolean;
}

function terminalInfoEqual(left: TerminalInfo, right: TerminalInfo): boolean {
  return (
    left.id === right.id &&
    left.name === right.name &&
    left.session === right.session &&
    left.running === right.running &&
    left.transport === right.transport
  );
}

function reconcileConcurrentTerminalChanges(
  baseline: TerminalInfo[],
  current: TerminalInfo[] | undefined,
  seed: TerminalInfo[],
): TerminalInfo[] {
  if (current === undefined) return seed;

  const baselineById = new Map(baseline.map((terminal) => [terminal.id, terminal]));
  const currentById = new Map(current.map((terminal) => [terminal.id, terminal]));
  const resultById = new Map(seed.map((terminal) => [terminal.id, terminal]));

  for (const terminalId of baselineById.keys()) {
    if (!currentById.has(terminalId)) resultById.delete(terminalId);
  }

  for (const [terminalId, terminal] of currentById) {
    const baselineTerminal = baselineById.get(terminalId);
    if (baselineTerminal === undefined || !terminalInfoEqual(baselineTerminal, terminal)) {
      resultById.set(terminalId, terminal);
    }
  }

  return [...resultById.values()];
}

async function fetchTerminalSnapshot(
  conversationId: string,
  signal?: AbortSignal,
): Promise<TerminalFetchResult> {
  const res = await authenticatedFetch(
    `/v1/sessions/${encodeURIComponent(conversationId)}/resources/terminals?order=asc&limit=1000`,
    { signal },
  );

  if (_SOFT_TERMINAL_LIST_STATUSES.has(res.status)) {
    return { terminals: readStoredTerminals(conversationId), authoritative: false };
  }

  if (!res.ok) {
    throw new Error(`terminals fetch failed: ${res.status} ${res.statusText}`);
  }

  const json: unknown = await res.json();
  if (
    !json ||
    typeof json !== "object" ||
    Array.isArray(json) ||
    !Array.isArray((json as Record<string, unknown>).data)
  ) {
    throw new Error("terminals fetch returned an invalid list response");
  }

  const rows = (json as { data: unknown[] }).data;
  const terminalsById = new Map<string, TerminalInfo>();

  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      continue;
    }
    const terminal = terminalInfoFromResource(row as Record<string, unknown>);
    if (terminal !== null && !terminalsById.has(terminal.id)) {
      terminalsById.set(terminal.id, terminal);
    }
  }

  const terminals = [...terminalsById.values()];

  if (rows.length > 0 && terminals.length === 0) {
    throw new Error("terminals fetch returned no addressable terminal rows");
  }

  return { terminals, authoritative: true };
}

/**
 * Fetch the current terminal resources for a conversation.
 *
 * A successful response is authoritative and replaces the persisted
 * inventory, including when the returned list is empty. Soft bootstrap
 * statuses retain and return the last-known session-storage snapshot.
 *
 * @param conversationId Session/conversation identifier.
 * @returns Authoritative terminals, or retained terminals when the
 * runner-backed endpoint is temporarily unavailable.
 * @throws Error for hard HTTP failures or malformed successful responses.
 */
export async function fetchTerminals(conversationId: string): Promise<TerminalInfo[]> {
  const result = await fetchTerminalSnapshot(conversationId);
  if (result.authoritative) writeStoredTerminals(conversationId, result.terminals);
  return result.terminals;
}

/**
 * Create (launch) a terminal for a conversation over HTTP.
 *
 * POSTs the server's terminal-create route, which gates the request on
 * the agent's declared ``terminals:`` names (400 otherwise) and
 * proxies the launch to the runner. The created terminal lands in the
 * same per-conversation registry the agent's ``sys_terminal_*`` tools
 * read, so it is immediately visible to the agent.
 *
 * :param conversationId: Session/conversation identifier,
 *     e.g. ``"conv_abc123"``.
 * :param terminal: Declared terminal name from the agent spec,
 *     e.g. ``"shell"`` (or a shell basename like ``"zsh"`` for a native
 *     session offering the host's installed shells).
 * :returns: The created terminal mapped to :class:`TerminalInfo`.
 * :raises Error: When the server rejects the create (e.g. the agent
 *     has no terminal access) or the launch fails.
 */
export async function createTerminal(
  conversationId: string,
  terminal: string,
): Promise<TerminalInfo> {
  // Random session key so repeated clicks launch fresh terminals —
  // the runner's launch is idempotent per (terminal, session_key), so
  // a fixed key would silently return the same terminal every time.
  const sessionKey = `u-${Math.random().toString(36).slice(2, 8)}`;
  const res = await authenticatedFetch(
    `/v1/sessions/${encodeURIComponent(conversationId)}/resources/terminals`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ terminal, session_key: sessionKey }),
    },
  );
  if (!res.ok) {
    let message = `terminal create failed: ${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      // Non-JSON error body — keep the status-line message.
    }
    throw new Error(message);
  }
  const info = terminalInfoFromResource((await res.json()) as Record<string, unknown>);
  if (info === null) {
    throw new Error("terminal create returned an unrecognized resource shape");
  }
  return info;
}

/**
 * Mutation hook around :func:`createTerminal`.
 *
 * On success the created terminal is merged into the terminals query
 * cache immediately (deduped by id), so the new tab appears without
 * waiting for the ``session.resource.created`` SSE round-trip — which
 * still arrives and dedupes as a no-op.
 *
 * :param conversationId: Session/conversation identifier.
 * :returns: TanStack mutation taking the declared terminal name.
 */
export function useCreateTerminal(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (terminal: string) => createTerminal(conversationId, terminal),
    onSuccess: (info) => {
      const key = terminalsQueryKey(conversationId);
      const current = queryClient.getQueryData<TerminalInfo[]>(key) ?? [];
      if (current.some((t) => t.id === info.id)) return;
      queryClient.setQueryData<TerminalInfo[]>(key, [...current, info]);
    },
  });
}

/**
 * Live terminals for a conversation.
 *
 * Two sources feed the same query cache, keyed by ``terminalsQueryKey``:
 *
 * 1. An authoritative HTTP seed (:func:`fetchTerminals`) that runs once
 *    on mount. This makes the Terminal pill reflect an already-running
 *    terminal on a fresh load / refresh, and self-heals the rail if a
 *    live ``session.resource.created`` event was missed (connection
 *    hiccup, or the event landing before the SSE subscription opened).
 *    Without it the pill could stay gray indefinitely despite a running
 *    terminal — there was previously no HTTP fallback or poll.
 * 2. Live SSE ``session.resource.{created,deleted}`` deltas, which the
 *    chatStore handler patches in via ``setQueryData``. These arrive
 *    from snapshot-on-connect, the REST endpoint
 *    (``POST /resources/terminals``), and the agent tools
 *    (``sys_terminal_launch`` / ``sys_terminal_close``) that the AP
 *    relay republishes onto the stream.
 *
 * ``staleTime: Infinity`` keeps steady-state reads from clobbering SSE data.
 * Persisted initial data is always revalidated on mount, and the query
 * reconciles creates, deletes, and metadata changes that reach the cache
 * while its HTTP snapshot is in flight.
 */
export function useTerminals(
  conversationId: string | null,
  options?: UseTerminalsOptions,
): UseTerminalsResult {
  const queryClient = useQueryClient();
  const reconcileWhilePending = options?.reconcileWhilePending ?? false;
  const queryKey =
    conversationId === null
      ? (["conversation", null, "terminals"] as const)
      : terminalsQueryKey(conversationId);
  const cachedAtRender =
    conversationId === null ? undefined : queryClient.getQueryData<TerminalInfo[]>(queryKey);

  const storedAtRender = conversationId === null ? undefined : readStoredTerminals(conversationId);

  const hasCachedInventory = cachedAtRender !== undefined;

  const hydrateFromStorage =
    !hasCachedInventory && storedAtRender !== undefined && storedAtRender.length > 0;

  // An existing query may contain stale SSE-era data even when it did not
  // originate from sessionStorage. Revalidate it on a fresh mount.
  const shouldRefetchExistingOnMount = hasCachedInventory || hydrateFromStorage;

  // The terminal list is SSE-primary: live `session.resource.{created,deleted}`
  // deltas (plus the mount seed) ARE the list, so a terminal becomes openable
  // the instant its `created` event lands — no waiting on the runner-liveness
  // poll. The `/health` poll (`runnerOnline`) is only a *corrector* for the
  // statuses the SSE stream can't deliver, applied on its liveness edges in the
  // effect below — it never continuously masks the SSE-driven list. Runner
  // liveness is poll-driven (the real-time push was removed upstream), so a
  // continuous mask would read stale-`false` during a cold/relaunch boot and
  // wrongly hide a terminal the SSE just delivered.
  const runnerOnline = useSessionRunnerOnline(conversationId ?? undefined);

  const terminalFetchSequence = useRef(0);

  // Track whether the most recent completed fetch was authoritative and how
  // many consecutive soft (non-authoritative) responses have been received.
  // The refetchInterval uses this to bound the soft-response retry window.
  // requestId ensures an aborted or superseded request does not overwrite
  // the observation produced by a newer request.
  const lastTerminalFetch = useRef<{
    conversationId: string | null;
    authoritative: boolean | undefined;
    consecutiveSoftFetches: number;
    requestId: number;
  }>({
    conversationId: null,
    authoritative: undefined,
    consecutiveSoftFetches: 0,
    requestId: 0,
  });

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const activeConversationId = conversationId!;
      const conversationKey = terminalsQueryKey(activeConversationId);
      const beforeFetch = queryClient.getQueryData<TerminalInfo[]>(conversationKey);

      const previousObservation = lastTerminalFetch.current;
      const previousSoftFetches =
        previousObservation.conversationId === activeConversationId
          ? previousObservation.consecutiveSoftFetches
          : 0;

      const requestId = ++terminalFetchSequence.current;

      // Clear the prior outcome before starting this attempt. A hard
      // failure must not inherit `authoritative: false` from an earlier
      // soft response and accidentally keep polling.
      lastTerminalFetch.current = {
        conversationId: activeConversationId,
        authoritative: undefined,
        consecutiveSoftFetches: previousSoftFetches,
        requestId,
      };

      try {
        const fetched = await fetchTerminalSnapshot(activeConversationId, signal);

        // A canceled or superseded request must not overwrite the
        // observation produced by a newer request.
        if (lastTerminalFetch.current.requestId === requestId) {
          lastTerminalFetch.current = {
            conversationId: activeConversationId,
            authoritative: fetched.authoritative,
            consecutiveSoftFetches: fetched.authoritative ? 0 : previousSoftFetches + 1,
            requestId,
          };
        }

        const seed = fetched.authoritative ? fetched.terminals : (beforeFetch ?? fetched.terminals);
        const current = queryClient.getQueryData<TerminalInfo[]>(conversationKey);
        return reconcileConcurrentTerminalChanges(beforeFetch ?? [], current, seed);
      } catch (fetchError) {
        if (lastTerminalFetch.current.requestId === requestId) {
          lastTerminalFetch.current = {
            conversationId: activeConversationId,
            authoritative: undefined,
            consecutiveSoftFetches: 0,
            requestId,
          };
        }
        throw fetchError;
      }
    },
    enabled: conversationId !== null,
    initialData: hydrateFromStorage ? storedAtRender : undefined,
    refetchOnMount: shouldRefetchExistingOnMount ? "always" : undefined,
    staleTime: Infinity,
    // One light retry covers a transient network blip during the
    // initial load without hammering an unreachable runner.
    retry: 1,
    // Self-heal a missed ``session.resource.created`` while a terminal is
    // spinning up: poll the authoritative endpoint until one appears, then
    // stop. Also re-polls when the runner is online but the last fetch
    // returned a soft non-authoritative snapshot (503 etc.), bounded by
    // MAX_CONSECUTIVE_SOFT_TERMINAL_FETCHES to prevent infinite polling.
    refetchInterval: (query) => {
      const observation = lastTerminalFetch.current;
      const appliesToConversation = observation.conversationId === conversationId;
      return terminalsReconcileInterval(
        reconcileWhilePending,
        query.state.data?.length ?? 0,
        runnerOnline,
        appliesToConversation ? observation.authoritative : undefined,
        appliesToConversation ? observation.consecutiveSoftFetches : 0,
      );
    },
  });
  // The poll corrects the SSE-driven list ONLY on runner-liveness edges — it
  // never masks continuously. Two corrections, both keyed off the edge so a
  // stale-`false` read during boot (before the runner has ever been seen up)
  // can't wipe a terminal the SSE just delivered:
  //
  //   - `→ true` (came online): re-read the authoritative endpoint to pick up
  //     a `session.resource.created` the SSE may have dropped. The queryFn
  //     unions, so a live SSE entry is never lost — this is purely additive.
  //   - `true → false` (confirmed stop): keep the last-known list mounted.
  //     TerminalView owns the lifecycle overlay and xterm buffer preservation;
  //     clearing this cache here would unmount it before the offline state can
  //     render. The next `→ true` correction refreshes the authoritative list.
  useEffect(() => {
    if (conversationId !== null && data !== undefined) {
      writeStoredTerminals(conversationId, data);
    }
  }, [conversationId, data]);

  const runnerObservation = useRef<{
    conversationId: string | null;
    online: boolean | undefined;
  }>({
    conversationId,
    online: runnerOnline,
  });

  useEffect(() => {
    const previous = runnerObservation.current;

    const conversationChanged = previous.conversationId !== conversationId;

    if (conversationId !== null && runnerOnline === true) {
      const key = terminalsQueryKey(conversationId);

      if (conversationChanged) {
        // Switching to an uncached conversation automatically starts its
        // first query. Switching to a stored/cached conversation may already
        // be refetching because of refetchOnMount. Only invalidate when no
        // request for the new key is active.
        const state = queryClient.getQueryState(key);
        if (state?.fetchStatus !== "fetching") {
          void queryClient.invalidateQueries({ queryKey: key, exact: true });
        }
      } else if (previous.online !== true) {
        // Same conversation recovered from unknown/offline state. The prior
        // request may have returned a retained soft result, so force a new
        // authoritative reconciliation.
        void queryClient.invalidateQueries({ queryKey: key, exact: true });
      }
    }

    runnerObservation.current = {
      conversationId,
      online: runnerOnline,
    };
  }, [conversationId, runnerOnline, queryClient]);
  return {
    // SSE-primary: the list is whatever the cache holds (seed + live deltas,
    // corrected on poll edges above). No continuous runner-online mask.
    terminals: data ?? [],
    isLoading,
    error: (error as Error | null) ?? null,
  };
}
