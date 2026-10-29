# Deploying to CML

This repo is structured as a CML Applied ML Prototype (AMP) via
[`.project-metadata.yaml`](../.project-metadata.yaml), so it can be imported
as a CML project in one step. That file (and [`launch_app.py`](../launch_app.py),
its Application entrypoint) stays at the repository root because CML reads
both from there directly. This page documents the deployment flow they drive.

1. Deploy a model with reliable tool calling on Cloudera AI Inference
   Service (for example Llama 3.1 70B Instruct) and copy its OpenAI-compatible
   base URL, ending in `/v1`.
2. In your CML workspace, create a new project from this Git repo (push this
   directory to a repo CML can reach first).
3. CML prompts for the environment variables declared in
   `.project-metadata.yaml`. Set `CAII_BASE_URL` and `CAII_MODEL_NAME`. Leave
   `CAII_API_KEY` blank to use the workload token CML mounts at `/tmp/jwt`.
   Optionally set `E2B_API_KEY` for an isolated sandbox.
4. On import, CML runs the `Install dependencies` and `Check synthetic network
   and sandbox` tasks, then starts the `Mobile NOC Agent` Application. The
   check task prints the before/after handover success rate and fails loudly
   if the scenario or sandbox is broken.
5. Open the Application and click **Handover success on GNB1042-C1 dropped
   this morning. Why?**

## Without the AMP flow

Create a project from the repo, open a Session, run `bash cdsw-build.sh`,
then create an Application with script `launch_app.py` and the environment
variables above.

## Sandbox choice

| `SANDBOX_PROVIDER` | Where the agent's code runs | Isolation | Needs |
| --- | --- | --- | --- |
| `local` | Subprocess in the Application container, with CPU-time and memory limits, a scratch directory and no secrets in its environment | None. Fine for this synthetic data only | Nothing |
| `e2b` | A fresh E2B microVM per call | Yes | `E2B_API_KEY`, outbound internet |
| `auto` (default) | `e2b` if `E2B_API_KEY` is set, else `local` | | |

## Hardware sizing

Per-task sizing (from `.project-metadata.yaml`):

| Task | CPU | Memory |
| --- | --- | --- |
| Install dependencies | 1 | 2 GB |
| Check synthetic network and sandbox | 1 | 2 GB |
| Mobile NOC Agent (Application) | 2 | 4 GB |

The Application does no local inference, so it has no GPU requirement of its
own. The GPU requirement is on the Cloudera AI Inference Service endpoint.

## State and restarts

The synthetic network, the agent's conversation and any pending approval are
held in memory per browser session. Restarting the Application resets the
scenario. The audit log is also appended to `output/audit.jsonl` in the
project.
