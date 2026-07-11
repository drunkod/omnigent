# T09 — Runner UX (Track 2 steps)

Web-side surface for remote-local runners, gated on the
`remote_local_runner` capability (`/v1/info`, live since `95d9988e`).
Server prerequisites are all in place: hosts API
(`omnigent/server/routes/hosts.py`), session create with
`host_id`/`workspace`/`local_runner_policy` (validated fail-loud since
`18bb38dc`), and binding labels in the session snapshot.

Steps are sequential within the track; the whole track is independent of
T08 close-out and T06b and can run in parallel with both.

1. `step-01-runner-list-fetch.md` — `/v1/hosts` types, fetch, `useHosts`
   hook, capability gate. Probe the real payload before typing.
2. `step-02-workspace-picker.md` — new-session picker (host → workspace →
   policy preset) + execution-mode badge from session labels.
3. `step-03-capability-dashboard.md` — read-only host capability panel.

Run web checks per slice:

```bash
cd web && npm test -- --run src/lib/remoteRunner.test.ts && npm run type-check
```

Done-when for the track: a flag-on server lets a user pair a host, pick a
workspace and policy at session create, see the local badge in the
header, and inspect host capabilities — with flag-off servers rendering
none of it.
