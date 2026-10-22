# AgentTrace MVP specification

## Problem and users

Developers debugging tool-using AI agents must often reconstruct what happened from scattered logs. A successful final response does not necessarily mean that every tool call was valid or successful, and a failed call alone does not establish why the agent made it. AgentTrace will analyze a local recording, identify narrowly defined observable problems, and package supporting evidence for review.

The primary users are Python developers building or maintaining agents and engineers investigating failed runs or writing regression cases. The MVP assumes they can produce AgentTrace JSONL themselves; framework-specific ingestion is not required. This is a proposed product scope, not a claim of uniqueness or an existing capability.

## Scope and non-goals

The first working MVP is an offline Python CLI that reads one versioned JSONL trace, validates its structure, applies the four rules below, prints a deterministic human-readable report, and exports a selected finding and its evidence as a redacted JSON file. It must work without an account, network access, model calls, or a running service. It analyzes recorded data only.

Non-goals: instrumenting agents; importing vendor or OpenTelemetry traces; a UI or server; production monitoring; LLM-as-judge; automatic root-cause determination; comparing agent versions; executing, replaying, mocking or calling tools; generating runnable tests; and complete JSON Schema support. The case file is reviewable input for a future test, not a runnable regression test or a promise of reproducibility.

## Trace format v1

UTF-8 JSON Lines: one JSON object per nonblank line, in recording order. Every event has `schema_version` equal to integer `1`, a nonempty unique `event_id`, a nonempty `trace_id`, a `type`, and an RFC 3339 timestamp with timezone in `timestamp`. All events in one file must share a `trace_id`. IDs are opaque strings, not paths. Duplicate IDs, mixed trace IDs, invalid JSON, missing required fields, invalid timestamps, unsupported versions or types, and invalid call lifecycle relationships are input errors: report line number and reason, produce no findings or case, and exit nonzero. Blank lines are ignored. A valid empty file is not a trace and is an input error.

Three event types are supported:

| Type | Required additional fields | Meaning |
| --- | --- | --- |
| `tool_schema` | `tool_name`, `parameters` | Schema available to subsequent calls with the same tool name, until another schema event for that name. |
| `tool_call` | `call_id`, `tool_name`, `arguments` | A call attempt; `arguments` is any JSON value. Call IDs are unique within the trace. |
| `tool_result` | `call_id`, `status` | Outcome of an earlier call. `status` is `success`, `error`, or `timeout`; optional `error_message` is a string. At most one result per call. |

Tool names and call IDs are nonempty strings. A result must reference an earlier call; a call without a result is valid but incomplete. Timestamps are evidence, not the ordering authority: file order determines schema selection and call sequence. No duration-based timeout is inferred.

`parameters` is a deliberately limited object-schema format: an object with `type: "object"`, optional `properties` mapping property names to objects containing only a `type` from `string`, `number`, `integer`, `boolean`, `object`, `array`, or `null`, optional `required` array of unique property names, and optional boolean `additionalProperties` (default `true`). Required names must be declared in `properties`. Nested values are checked only for their top-level type; there are no nested constraints, coercion, formats or `$ref`. `number` accepts JSON integers and fractional numbers; `integer` accepts mathematically integral JSON numbers; booleans are neither. Unknown keywords, invalid schemas or unsupported types are input errors, not argument failures. JSON object key order is immaterial.

Example (one event per line):

```jsonl
{"schema_version":1,"event_id":"s1","trace_id":"t1","timestamp":"2026-01-01T10:00:00Z","type":"tool_schema","tool_name":"lookup","parameters":{"type":"object","properties":{"id":{"type":"string"}},"required":["id"],"additionalProperties":false}}
{"schema_version":1,"event_id":"c1","trace_id":"t1","timestamp":"2026-01-01T10:00:01Z","type":"tool_call","call_id":"call-1","tool_name":"lookup","arguments":{"id":42}}
{"schema_version":1,"event_id":"r1","trace_id":"t1","timestamp":"2026-01-01T10:00:02Z","type":"tool_result","call_id":"call-1","status":"error","error_message":"invalid ID"}
{"schema_version":1,"event_id":"c2","trace_id":"t1","timestamp":"2026-01-01T10:00:03Z","type":"tool_call","call_id":"call-2","tool_name":"lookup","arguments":{"id":42}}
{"schema_version":1,"event_id":"r2","trace_id":"t1","timestamp":"2026-01-01T10:00:04Z","type":"tool_result","call_id":"call-2","status":"timeout"}
```

## Detection and reporting

Rules operate independently; a call may have multiple findings. Each finding has a deterministic ID derived from its rule and ordered evidence event IDs, rule ID, severity, observation, evidence references (`event_id` and JSONL line number), and a concrete recommendation. IDs must be stable for the same trace and rule version; report ordering is by first evidence line, then rule ID. Evidence references identify records, not proof of causation. The report includes rule coverage and incomplete calls even when there are no findings. Do not print raw arguments or error messages by default.

| Rule | Trigger and evidence | Severity | Recommendation |
| --- | --- | --- | --- |
| `invalid_arguments` | A call violates the most recent preceding schema for its tool: arguments are not an object, a required property is missing, a declared property has the wrong type, or an extra property is present when `additionalProperties` is false. Reference schema and call; report property paths and violation kinds without values. | warning | Correct the arguments or update the schema if the contract is wrong. |
| `execution_error` | A recorded result has `status: "error"`. Reference call and result. | error | Inspect the tool's recorded error and implementation or dependency logs locally. |
| `timeout` | A recorded result has `status: "timeout"`. Reference call and result. | error | Inspect the timeout configuration and tool latency or availability. |
| `repeated_calls` | Three or more consecutive `tool_call` events, ignoring schema and result events, have the same tool name and structurally equal arguments. Object key order is ignored; array order and JSON types matter. Emit one finding per maximal run and reference every call. | warning | Inspect whether retries were intended and whether a retry limit or backoff is appropriate. |

Repeated calls are an observed pattern, not necessarily a failure: intentional retries can be legitimate. A recorded `error` or `timeout` establishes only the reported outcome, not its underlying cause. Recommendations are checks, not diagnoses. No rule should claim the agent's intent, a causal chain, or that a final user task failed.

When no preceding schema exists, argument validity is **unknown**, not valid or invalid; report the call as not evaluated for that rule. A schema arriving after a call is not applied retroactively. A missing result is **unknown/incomplete**, not success, error, or timeout. Report these coverage gaps with event references and counts separately from findings. A clean report means only that no enabled rule triggered on the available evidence. Unsupported or malformed schemas fail input validation rather than silently producing a clean result.

## Portable failure case v1

`export-case` selects exactly one finding ID from a fresh analysis of the input and writes a UTF-8 JSON object with:

```json
{
  "case_version": 1,
  "trace_id": "t1",
  "finding": {"id": "FINDING_ID", "rule_id": "execution_error", "severity": "error", "observation": "Tool execution reported an error.", "evidence_event_ids": ["c1", "r1"], "recommendation": "Inspect the tool's recorded error and implementation or dependency logs locally."},
  "events": [
    {"schema_version": 1, "event_id": "c1", "trace_id": "t1", "timestamp": "2026-01-01T10:00:01Z", "type": "tool_call", "call_id": "call-1", "tool_name": "lookup", "arguments": "[REDACTED]"},
    {"schema_version": 1, "event_id": "r1", "trace_id": "t1", "timestamp": "2026-01-01T10:00:02Z", "type": "tool_result", "call_id": "call-1", "status": "error", "error_message": "[REDACTED]"}
  ],
  "redaction": {"policy": "default-v1", "fields": ["c1:arguments", "r1:error_message"]},
  "limitations": ["Payloads were redacted; this case is not executable or sufficient to reproduce the run."]
}
```

`FINDING_ID` is illustrative; an actual export contains the ID printed by analysis. Include only referenced evidence events in original order, plus the finding and explicit redaction/limitations metadata. This is an evidence envelope, not a trace to re-ingest: redacted values need not satisfy the trace schema. Missing context is not invented. Reject an unknown finding ID, invalid input, or an existing output path; never overwrite it. Export must not execute any code or tools contained in the trace.

## CLI contract

```sh
agenttrace analyze ./trace.jsonl
agenttrace export-case ./trace.jsonl --finding FINDING_ID --output ./case.json
```

`analyze` exits `0` for a valid trace, whether or not findings exist, and prints finding IDs and coverage gaps. Input, I/O, or usage errors exit `2` with a concise diagnostic on stderr; no partial report or case is produced. `export-case` exits `0` on success and `2` on errors. This MVP does not use finding presence as a CI failure signal.

## Privacy and untrusted input

All processing is local and offline; no telemetry or uploads. Trace contents can contain secrets, personal data, hostile strings and misleading instructions. Treat every field as data: never evaluate code, follow URLs, resolve external schema references, invoke tools, or interpret trace text as instructions. Escape terminal control characters in all displayed user-controlled strings, and bound file size, line length, event count and JSON nesting with documented conservative limits; reject inputs exceeding them rather than truncating evidence silently.

The initial parser limits are 10 MiB per file, 1 MiB per physical line (both measured in UTF-8 bytes, including line endings), 10,000 nonblank records, and 64 levels of JSON objects/arrays (the outer object counts as level one). Limits are inclusive. An empty or blank-only file is reported at line 1; other errors identify the physical line where they are detected. These conservative defaults can be revisited as real trace sizes become clearer.

Default export replaces every call's entire `arguments`, every `error_message`, and every schema's `parameters` with `[REDACTED]`; record each replacement in `redaction.fields`. Do not offer a raw export in this MVP. IDs, tool names, timestamps, status, rule paths and metadata can still be sensitive: warn users before sharing, and state that this policy is not a guarantee of anonymization. The local source trace remains unchanged. Do not log payloads in errors, temporary files or diagnostics; write the case with restrictive permissions where supported and avoid partial files on failure. Local reports also omit payload values and error messages; property names and identifiers remain visible and may themselves be sensitive.

## Acceptance criteria and pytest matrix

Acceptance: the example trace yields argument, execution-error and timeout findings with correct evidence, while two calls do not meet the repetition threshold. A three-call repetition produces one warning. Findings and ordering are deterministic; missing schema and missing result are explicitly unknown. A selected case is valid JSON, contains only its referenced events, applies default redaction and never executes trace content. Invalid input fails without partial output. Both commands run offline and leave the source untouched.

| pytest area | Cases and expected outcome |
| --- | --- |
| Parsing and lifecycle | Valid JSONL and blank lines; malformed JSON, unsupported version/type, bad timestamps, duplicate IDs, mixed traces, orphan or duplicate results, invalid schema and resource limits fail with line-aware diagnostics. |
| Arguments | Missing required field, wrong type, non-object arguments and disallowed extras produce findings with schema/call evidence. Valid arguments, optional fields, permitted extras and reordered keys do not. Check integer/number and boolean edge cases. |
| Missing evidence | No preceding schema, schema only after call, and missing result are coverage gaps, not invalid arguments or timeouts. |
| Results | Explicit error and timeout trigger their respective findings; success does not. Error text mentioning a timeout with `status: error` remains an error, not a timeout. |
| Repetition and false positives | Three identical consecutive calls yield one finding; two do not. Different tool, argument value, JSON type or array order breaks a run; object key order does not. Interspersed results do not break it. Intentional retries are still labeled a pattern, not a proven defect. |
| Report and export | Stable IDs/order and correct line references; select each rule; unknown ID and existing output fail; no partial output. Redaction covers arguments, schemas and errors; no unreferenced events or raw payloads leak into reports, diagnostics or case. |
| Safety | Strings containing terminal escapes, shell commands, URLs and prompt instructions remain inert; network/tool execution is never invoked. Verify input stays unchanged and output permissions where supported. |

## Milestones

1. Define fixtures and implement bounded JSONL parsing, lifecycle validation and schema subset with tests.
2. Add deterministic detection, evidence references, coverage reporting and false-positive tests.
3. Add redacted case export and CLI error handling; test hostile input and offline behavior.
4. Run the full pytest suite and exercise the two commands on a small real, sanitized trace; document limitations and collect developer feedback before expanding scope.
