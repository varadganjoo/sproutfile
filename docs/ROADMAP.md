# Things a file might learn to do

The working release supports explicit local sources, five block types, cross-file dependencies, provenance hashes, short history, agent jobs, and guarded per-file publication.

Next experiments, not implemented features:

1. **Review before refresh.** Show an intelligible preview of proposed prose and the particular facts that changed. Let a person accept or reject one update without losing the proposal.
2. **Agent authoring.** An agent turns a request into a small declarative recipe, with a source and permission preview. Test whether people can understand the resulting promise.
3. **Better evidence.** Compare claims with source passages and distinguish a missing fact from a contradicted fact. Exact substring quotes are only the starting point.
4. **Real sources.** Explicit adapters for public feeds and user-selected local files, with expiry and failure policies. No implicit account access.
5. **Many agents, one output.** Try an agent handoff between different tools using the same job format and freshness checks.
6. **Portable folders.** A documented bundle for the artifact and chosen sources, with fresh local trust and a useful read-only fallback.

First success criterion: someone other than the author uses one file for a week and finds it easier to maintain than their current workflow. Stars are nice; an output that survives a changed assumption is the thing to test.
