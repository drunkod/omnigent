from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sse_path = ROOT / "web/src/lib/sse.ts"
sse = sse_path.read_text(encoding="utf-8")
old = '''    const localActionWirePresent =
      p.local_action !== undefined ||
      p.kind === "read_file" ||
      p.kind === "write_file" ||
      p.kind === "list_dir" ||
      p.kind === "run_shell" ||
      p.kind === "apply_patch";
'''
new = '''    const localActionWirePresent =
      p.local_action !== undefined ||
      (typeof p.kind === "string" &&
        (p.policy_mode === "manual" ||
          p.policy_mode === "assisted" ||
          p.policy_mode === "auto"));
'''
if old not in sse:
    raise RuntimeError("SSE local-action envelope marker was not produced")
sse_path.write_text(sse.replace(old, new, 1), encoding="utf-8")

# Migrate old component fixtures that intentionally exercised the prior
# `{kind, policyMode}` shape. Production objects now require the bounded
# contract fields.
pattern = re.compile(
    r'localAction=\{\{\s*kind: "(?P<kind>write_file|run_shell)",\s*'
    r'policyMode: "(?P<mode>manual|assisted|auto)"\s*\}\}',
    re.S,
)
for path in (ROOT / "web/src").rglob("*.test.tsx"):
    text = path.read_text(encoding="utf-8")

    def replacement(match: re.Match[str]) -> str:
        return (
            'localAction={{\n'
            '          version: 1,\n'
            f'          kind: "{match.group("kind")}",\n'
            f'          policyMode: "{match.group("mode")}",\n'
            '          pathSummary: [],\n'
            '          diffTruncated: false,\n'
            '          riskFlags: [],\n'
            '        }}'
        )

    updated = pattern.sub(replacement, text)
    if updated != text:
        path.write_text(updated, encoding="utf-8")

print("T11 compatibility migrations completed")
