# Mobile NOC Agent Demo

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](requirements.txt)
[![Cloudera AI](https://img.shields.io/badge/Cloudera%20AI-Inference%20Service-F96702.svg)](.project-metadata.yaml)

## Table of Contents

- [Overview](#overview)
- [Use Case](#use-case)
- [Key Features](#key-features)
- [Quickstart](#quickstart)
- [Architecture / Software Components](#architecture--software-components)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Hardware Requirements](#hardware-requirements)
- [Sandbox Options: E2B and Pyodide](#sandbox-options-e2b-and-pyodide)
- [Access Control (RBAC)](#access-control-rbac)
- [Moving to a Real Network](#moving-to-a-real-network)
- [License](#license)
- [Disclaimer](#disclaimer)

## Overview

A LangGraph agent that investigates a 5G radio network problem the way a NOC
engineer would. It reads alarms, KPIs, cell configuration and topology,
analyses them with code it writes and runs in a sandbox, and proposes a
configuration fix. Nothing changes until a person approves the exact diff.

Everything runs against a synthetic network, so the demo is safe to run
anywhere. The LLM is served by Cloudera AI Inference Service, and the app runs
as a single Cloudera AI Workbench Application.

## Use Case

**The staged fault.** At 07:02 a small cell, `SC1188-C1`, is commissioned
inside the coverage of `GNB1042-C1` with PCI 141. Neighbour `GNB1043-C1`
already uses PCI 141, so `GNB1042-C1` now has two neighbours on the same PCI
(PCI confusion). UEs near the small cell get handed to the wrong cell, and
handover success on `GNB1042-C1` falls from about 99% to about 82% from the
07:15 ROP onward. No alarm fires; the active alarms are unrelated background
noise.

**What the agent does.**

1. Checks alarms and KPIs, and sees the handover drop on `GNB1042-C1`.
2. Pulls per-neighbour handover counters. The failures concentrate on target
   PCI 141.
3. Runs pandas code in the sandbox to confirm when the drop started and which
   relation it sits on.
4. Finds the 07:02 commissioning in the CM change log, and the PCI clash in
   the neighbour list.
5. Proposes a new PCI for `SC1188-C1` (for example 401: unused within two hops,
   and with a different mod-3 value from its neighbour).
6. The run pauses and the engineer sees the diff and the guardrail checks,
   then approves or rejects.
7. After approval the change is applied, the clock moves one ROP, and the
   agent confirms recovery and writes a ticket note.

The counters are generated from the configuration that was live at each ROP,
not scripted, so any PCI that removes the conflict fixes it and any PCI that
doesn't leaves the fault in place.

## Key Features

- **Human approval on every change.** `propose_cm_change` calls LangGraph's
  `interrupt()`; the graph state is checkpointed until the engineer decides.
- **Guardrails before approval.** An attribute allowlist, value ranges, PCI
  uniqueness within two hops (blocking), a mod-3 check (warning), and a change
  budget per session.
- **Sandboxed analysis.** The agent's own code runs in E2B, or in a limited
  local subprocess for synthetic data, never in the process that holds the
  OSS tools. Tool results are passed in as CSV datasets, so large tables never
  go through the model.
- **Audit log** of every tool call and decision, in the UI and in
  `output/audit.jsonl`.
- **NOC console UI.** Network health tiles, a clickable sector map coloured by
  handover success, a KPI trend with change markers, an investigation progress
  strip and an approval card with the guardrail results and config diff.
- **Presenter mode** (sidebar toggle) that draws the PCI clash on the map,
  marks the commissioning event on the KPI chart and adds a root-cause tab.

## Quickstart

### In Cloudera AI Workbench

See [deploy/cml-deployment.md](deploy/cml-deployment.md). In short: create a
project from this repo as an AMP, set `CAII_BASE_URL` and `CAII_MODEL_NAME`,
and open the `Mobile NOC Agent` Application.

### Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set CAII_BASE_URL, CAII_MODEL_NAME and CAII_API_KEY or CDP_TOKEN

python scripts/check_scenario.py   # no LLM needed: checks the fault, guardrails, fix and sandbox
pytest                             # includes a full graph run with a scripted model
streamlit run app.py
```

Any OpenAI-compatible endpoint with tool calling works for local runs.

## Architecture / Software Components

![Functional architecture: the NOC engineer talks to the Streamlit app; the LangGraph agent reasons with the LLM, reads FM/PM/CM through trusted tools, runs analysis code in an untrusted sandbox, and changes the network only through propose_cm_change after a person approves](assets/architecture.png)

Black arrows are requests and data; green arrows are the change path, which
needs a person to approve. The agent's own code runs only in the sandbox
(orange), and everything in the dotted box is synthetic and replaced at
go-live.

> **Scope of the network model.** The diagram shows the target scope, with
> transport and 5G core alongside the RAN. The current code models **only the
> radio side**: 12 gNBs, 36 NR cells and one small cell, with their CM
> attributes, neighbour relations, per-ROP PM counters and FM alarms. No
> transport (backhaul) or core (AMF, SMF, UPF) elements, alarms or counters
> are generated yet. The sandbox and guardrail boxes show options
> as well as what is built; see
> [Sandbox Options](#sandbox-options-e2b-and-pyodide) and
> [Access Control](#access-control-rbac) for what is in the code today.

| Component | File | Notes |
| --- | --- | --- |
| UI | `app.py`, `launch_app.py`, `src/ui/` | Streamlit with Altair charts, bound to `127.0.0.1:$CDSW_APP_PORT` |
| Agent | `src/agent.py` | `create_react_agent`, system prompt, in-memory checkpointer |
| LLM client | `src/llm.py`, `src/config.py` | `ChatOpenAI` against CAII; key from `CAII_API_KEY`, `/tmp/jwt`, or `CDP_TOKEN` |
| Read tools | `src/tools/read_tools.py` | Alarms, KPIs, handover relations, neighbours, cell config, CM changes |
| Sandbox tool | `src/tools/sandbox_tool.py`, `src/sandbox/` | `e2b` or `local` |
| Change tool | `src/tools/change_tool.py`, `src/tools/guardrails.py` | Checks, diff, `interrupt()`, apply |
| Mock OSS | `src/network/oss.py` | One method per REST endpoint; swap for a real adapter |
| Network model | `src/network/model.py`, `pm.py`, `fm.py` | 12 gNBs, 36 macro cells, 15-minute ROP counters, alarms |
| Scenario engine | `src/network/scenarios.py` | Stages the fault through a config event only |

## Repository Structure

```
.project-metadata.yaml   AMP manifest (env vars, tasks, Application)
METADATA.yaml            Blueprint catalog metadata
cdsw-build.sh            Dependency install for CML
launch_app.py            CML Application entrypoint
app.py                   Streamlit UI
src/                     Agent, tools, sandbox, synthetic network
scripts/                 install_dependencies.py, check_scenario.py, check_endpoint.py
tests/                   Network, guardrail and full-graph tests
deploy/                  CML deployment guide
assets/                  Architecture diagram
output/                  Audit log (git-ignored)
```

## Prerequisites

- A Cloudera AI Workbench project with Python 3.10 or later.
- A model on Cloudera AI Inference Service with **tool calling** enabled.
  The default is `nvidia/nemotron-3-super-120b-a12b`; any strong model with
  tool calling works, while 8B models often lose track of a multi-step
  investigation. `python scripts/check_endpoint.py` confirms the endpoint
  returns tool calls.
- Optional: an E2B API key and outbound internet for the isolated sandbox.

## Hardware Requirements

The Application needs 2 vCPU and 4 GB memory, and no GPU. See
[deploy/cml-deployment.md](deploy/cml-deployment.md#hardware-sizing).

## Sandbox Options: E2B and Pyodide

The agent's analysis code always runs through `run_python`, which calls the
provider chosen by `SANDBOX_PROVIDER` (see [src/sandbox/](src/sandbox/)).

| Provider | Status | Isolation | Needs |
| --- | --- | --- | --- |
| `local` | Built in | None: a subprocess with CPU and memory limits | Nothing |
| `e2b` | Built in | A fresh microVM per call | E2B API key, outbound internet |
| `pyodide` | Not built yet; steps below | WebAssembly, no file or network access unless granted | Deno, a Pyodide package cache |

### Use E2B

1. Create an API key at [e2b.dev](https://e2b.dev).
2. Make sure the workspace can reach `*.e2b.dev` over HTTPS. Some Cloudera AI
   workspaces block outbound internet; ask your platform team to allow it.
3. Set `E2B_API_KEY`, and `SANDBOX_PROVIDER` to `e2b` (or leave it at `auto`,
   which picks E2B whenever a key is set). In an AMP, set them in the project's
   environment variables, then restart the Application.
4. Check it from a Session: `python scripts/check_scenario.py` should print
   `Sandbox (e2b): sandbox ok, rows = 2`. The sidebar in the app shows
   `e2b` as an isolated sandbox.

`e2b-code-interpreter` is already in `requirements.txt`. Only the datasets the
agent names in `run_python` are uploaded, and nothing else (no credentials,
no OSS access) goes into the microVM.

### Add a Pyodide sandbox

Pyodide is CPython compiled to WebAssembly. It runs inside the workspace, so
no data leaves it, and code in it cannot see the host's files, environment
variables or network unless you grant them. It is not built into this repo
yet. To add it:

1. **Install a JavaScript runtime and the Python wrapper.** The simplest
   route is `langchain-sandbox`, which runs Pyodide under Deno. Add to
   `cdsw-build.sh`:

   ```bash
   curl -fsSL https://deno.land/install.sh | sh -s -- -y
   export PATH="$HOME/.deno/bin:$PATH"
   pip install langchain-sandbox
   ```

   and add `langchain-sandbox` to `requirements.txt`. Make sure the
   Application's `PATH` includes `~/.deno/bin`.
2. **Write the provider** as `src/sandbox/pyodide.py`. It must have the same
   `name`, `isolated` and `run(code, files, timeout_s)` as the other providers.
   Pyodide has an in-memory file system, so the datasets can be written into
   it at the start of the run:

   ```python
   import asyncio

   from src.sandbox import SandboxResult


   class PyodideRunner:
       name = "pyodide"
       isolated = True

       def run(self, code: str, files: dict[str, str], timeout_s: int = 30) -> SandboxResult:
           from langchain_sandbox import PyodideSandbox  # optional dependency

           setup = "import os\n" + "".join(
               f"os.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
               f"open({path!r}, 'w').write({content!r})\n"
               for path, content in files.items()
           )
           # allow_net lets Pyodide fetch pandas the first time; see step 4.
           sandbox = PyodideSandbox(allow_net=True)
           result = asyncio.run(asyncio.wait_for(sandbox.execute(setup + code), timeout_s))
           error = None if result.status == "success" else (result.stderr or "execution failed")
           return SandboxResult(result.stdout or "", result.stderr or "", error)
   ```

   Check the field names against the `langchain-sandbox` version you
   install. Streamlit already runs an event loop in some versions; if
   `asyncio.run` complains, run the call in a worker thread.
3. **Register it.** In `get_sandbox()` in
   [src/sandbox/\_\_init\_\_.py](src/sandbox/__init__.py), add a `pyodide`
   branch that returns `PyodideRunner()`. Add `pyodide` to the
   `SANDBOX_PROVIDER` description in `.project-metadata.yaml` and
   `.env.example`, then set `SANDBOX_PROVIDER=pyodide`.
4. **Plan for packages.** Pyodide downloads `pandas` and `numpy` on first
   use. On a workspace without internet access, serve a Pyodide package
   mirror inside your network and point Pyodide at it, or pre-populate its
   cache in the runtime image. Only packages built for Pyodide are available;
   pure-Python analysis with pandas and numpy is all this demo needs.
5. **Test it.** `python scripts/check_scenario.py` runs pandas in whatever
   sandbox is configured. Expect the first call to take a few seconds while
   Pyodide starts.

## Access Control (RBAC)

**What the code does today.** Every change needs a click on **Approve**, the
guardrails block disallowed attributes and invalid values, and a session can
make at most three changes (`MAX_CHANGES_PER_SESSION` in
[src/tools/guardrails.py](src/tools/guardrails.py)). The approver's name is
taken from the request headers (`Remote-User`, `X-Forwarded-User`,
`X-Auth-Request-User`) or `HADOOP_USER_NAME`, and recorded in the audit log.
There are **no roles**: anyone who can open the Application can approve.

To add role-based access:

1. **Limit who can open the app.** In Cloudera AI Workbench, keep the project
   private, add only the people who need it as collaborators, and leave
   *Allow Unauthenticated Access* off in the Application settings. This is the
   first and strongest control.
2. **Confirm the user identity.** Print `st.context.headers` once in the app
   and check which header your workspace's proxy sets to the signed-in user.
   Use only that header in `approver_name()` in [app.py](app.py), so a
   user can't claim another identity through a header the proxy doesn't
   overwrite.
3. **Define roles.** For example, add environment variables
   `NOC_APPROVERS` and `NOC_VIEWERS` (comma-separated usernames, or group
   names if you look groups up in your directory). Read them in
   `src/config.py`.
4. **Enforce in the UI.** In `render_approval()` in `app.py`, disable
   **Approve** and show who may approve when `approver_name()` is not in
   `NOC_APPROVERS`. Viewers can still ask questions and see the evidence.
5. **Enforce in the tool as well.** The UI check alone can be bypassed. In
   `propose_cm_change` ([src/tools/change_tool.py](src/tools/change_tool.py)),
   after `interrupt()` returns, treat the decision as rejected unless its
   `approver` is in `NOC_APPROVERS`, and write that outcome to the audit log.
6. **Scope by attribute or risk (optional).** Map roles to subsets of
   `ALLOWED_ATTRIBUTES` (for example, RF optimisers may change PCI and
   mobility offsets, others only offsets), or require a second approver for
   high-risk attributes by calling `interrupt()` twice with different
   approvers.
7. **In production, enforce at the OSS as well.** Give the OSS adapter a
   service account that can write only the managed objects and attributes
   the agent is allowed to change, and link each approval to a change ticket.
   The agent should never hold administrator credentials.

## Moving to a Real Network

| Demo piece | Production replacement |
| --- | --- |
| `MockOSS` | An adapter for your OSS/EMS northbound API (REST, NETCONF/YANG), usually run as a small service inside the management network that holds the credentials |
| Scenario engine | Removed |
| `local` sandbox | E2B or a self-hosted sandbox, if data may not leave your network |
| In-memory checkpointer | A persistent saver (e.g. Postgres) so paused approvals survive restarts |
| Audit file | Your central audit store; link approvals to change tickets |
| Change tool | Add your MOP checks, maintenance windows and automatic rollback |

## License

Apache 2.0. See [LICENSE](LICENSE).

## Disclaimer

This is a demo. The network, alarms and counters are synthetic. The local
sandbox mode is not a security boundary.
