# Prior art and the bet

Research checked on 16 October 2026. This is a bounded public search, not proof that an idea has never existed. Please open an issue with closer implementations. We will update the comparison and credit them.

## The user-visible bet

An agent can hand you a readable file that keeps its purpose, source-bound recipes, current values, and continuation jobs together. Later, you or a different agent can maintain the same output without reconstructing the original conversation. Local permissions remain outside the shared file.

The prototype combines a single portable HTML artifact, explicit block dependencies, selective invalidation, cross-file propagation, and a provider-independent agent proposal interface. Whether that combination is useful enough to deserve its own format is the experiment. The primitives are established.

| Neighbor | Established overlap | What this prototype tests |
| --- | --- | --- |
| [Active documents research, 1998](https://www.diva-portal.org/smash/get/diva2%3A832878/FULLTEXT01.pdf) | Documents with behavior, rather than inert text | A contemporary agent continuation workflow with an inert shareable view and separate local grants. We make no claim to invent active documents. |
| [Letta Agent File](https://www.letta.com/blog/agent-file/) | Portable agent state and continuity | The artifact is the human-readable output; each block has an explicit update recipe. Sproutfile is not a full agent-state export. |
| [Hermes live dashboards](https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/productivity/productivity-live-dashboard) | Agents maintain HTML/data outputs through ongoing workflows | Put the continuation contract inside each readable file, with dependencies between files and no required hosted agent. |
| [Reactive Composite Memory specification](https://github.com/critical-insight-ai/rcm-spec) | Reactive updates and structured context | Maintain end-user outputs as portable files rather than primarily maintaining agent context. |
| Spreadsheets, notebooks, and build systems | Dependency graphs, cached computation, and selective recomputation | Let deterministic blocks and agent-authored prose coexist in the same readable, inspectable handoff. This is an interaction and packaging hypothesis, not a new graph algorithm. |

These differences describe the intended scope of Sproutfile; they are not claims that neighbors lack every similar feature. Product capabilities can change after this check.

## Ideas discarded during exploration

Several directions looked promising until targeted searches found close existing work:

- Rehearsing tool actions against shadow state: [Shadow MCP](https://github.com/shadow-mcp/shadow-mcp) and [ChronoMCP](https://github.com/chronomcp/chronomcp).
- Causal replay of agent failures: [causal-agent-replay](https://github.com/jaineet17/causal-agent-replay).
- Compiling repeated agent reasoning into reusable execution: [AgentJIT](https://github.com/agent-jit/AgentJIT).
- Tool perturbation/fuzzing: [ToolFuzz](https://github.com/eth-sri/ToolFuzz).
- Translating model-to-model KV state: [C2C](https://github.com/thu-nics/C2C).
- Private agents negotiating social plans: [Shadownet](https://sh4dow.org/).
- Acting only when all surviving interpretations agree: [2016 work on unanimity](https://nlp.stanford.edu/pubs/khani2016unanimity.pdf).

We did not implement those directions and present them as new inventions.

## What would falsify this bet?

- People cannot understand what a file will read or change before trusting it.
- The continuation recipe creates more work than it saves compared with a small script or an existing scheduled agent.
- Agent prose cannot be reviewed effectively when its inputs change.
- Portability requires hidden services or private state that the file fails to describe.
- A close existing project already provides the same workflow better.

No benchmark or adoption result answers those questions yet. A three-file picnic is a starting experiment, not evidence of a field-wide breakthrough.
