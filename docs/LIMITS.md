# Limits and local trust

This is a prototype of a file and continuation workflow, not a service that guarantees ongoing responsibility. A snapshot can become stale whenever the runtime is stopped. Reopening the HTML does not contact sources or start an agent.

## Permissions

`trust` records a manifest hash and the absolute folder root in `.sprout-grants.json`. Source paths and destinations stay in that folder. Trust permits the artifact's declared local reads and its refresh; an agent block's selected input values may be sent to the local model you explicitly choose or to an agent you separately give the job to. Inspect sources before trusting.

The grant store is a convenience boundary, not an operating-system sandbox. A process with write access to your folder can change it. Do not use Sproutfile to isolate hostile code, run as an administrator, or store secrets in a document intended for sharing. Last values, quotes, source paths, and history are part of the shareable HTML.

Imported caches are not accepted as fresh merely because the manifest is trusted. The first refresh recomputes them. Recipe edits require new trust. Copying a grant store to another folder does not grant access there. Symlinks and junctions are refused by the runtime, but a malicious concurrent local process can still race filesystem checks.

## Writes and failures

The folder lock serializes cooperating Sproutfile commands. Missing inputs, invalid recipes, stale proposals, cycles, and generator failures normally leave existing artifacts untouched because planning finishes before publication. Each replacement uses a temporary file, fsync, and `os.replace`.

This is **not a multi-file transaction**. A disk error, crash, or source edit during the publication window can leave some files refreshed and others old. Source and destination checks reduce accidental overwrites but do not eliminate time-of-check/time-of-use races. A crash can leave `.sprout.lock`; verify no Sproutfile process is running before removing that stale lock. There is no automatic lock stealing or rollback command. Keep important folders under version control or backed up.

The generated HTML view is checked against its embedded state. Hand editing the rendered document causes a refusal. It is not an authenticated signature: a local process can replace both state and HTML. A source's correctness, availability, and interpretation are outside the runtime's guarantees.

## Generated prose

The runtime enforces input freshness, output shape, character limits, and exact source quotations. It does not verify every claim, resolve contradictory sources, infer dependencies, or enforce a natural-language goal. Agent-authored text requires review. Keep consequential outputs as drafts.

## Scope

No remote sources, credentials, shell evaluation, message sending, booking, daemon installation, built-in autonomous planning, or model installation. No measured claim about model-call savings on real workloads, superiority over existing tools, or adoption. The demo's zero-call result is specific to its deterministic recipes.
