"""
Settings for the Mobile NOC Agent demo, read from environment variables.

In Cloudera AI Workbench these are set on the project or Application (see
.project-metadata.yaml). For local development, copy .env.example to .env.

The LLM is any OpenAI-compatible chat endpoint that supports tool calling,
normally a model served by Cloudera AI Inference Service.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is only needed for local runs
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

JWT_FILE = os.environ.get("CDSW_APIV2_JWT_FILE", "/tmp/jwt")


class TokenUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    caii_base_url: str
    caii_model_name: str
    llm_temperature: float
    sandbox_provider: str          # "auto" | "e2b" | "local"
    sim_seed: int
    audit_log_path: Path

    @property
    def llm_configured(self) -> bool:
        return bool(self.caii_base_url and self.caii_model_name)


def load_settings() -> Settings:
    return Settings(
        caii_base_url=os.environ.get("CAII_BASE_URL", "").strip(),
        caii_model_name=os.environ.get("CAII_MODEL_NAME", "").strip(),
        llm_temperature=float(os.environ.get("LLM_TEMPERATURE", "0.1")),
        sandbox_provider=os.environ.get("SANDBOX_PROVIDER", "auto").strip().lower(),
        sim_seed=int(os.environ.get("SIM_SEED", "7")),
        audit_log_path=Path(os.environ.get("AUDIT_LOG_PATH", OUTPUT_DIR / "audit.jsonl")),
    )


def get_api_key() -> str:
    """Key for the Cloudera AI Inference endpoint.

    Order: CAII_API_KEY, then the workload JWT that Cloudera AI Workbench
    mounts into every Session, Job and Application, then CDP_TOKEN for local
    development. Call this per request: the JWT rotates.
    """
    if os.environ.get("CAII_API_KEY"):
        return os.environ["CAII_API_KEY"]

    delay, last_detail = 0.4, "file does not exist"
    for attempt in range(6):
        try:
            with open(JWT_FILE, encoding="utf-8-sig") as f:
                raw = f.read()
            data = json.loads(raw[raw.find("{"):]) if "{" in raw else {}
            if data.get("access_token"):
                return data["access_token"]
            last_detail = "file had no access_token"
        except FileNotFoundError:
            break
        except (OSError, json.JSONDecodeError) as exc:
            last_detail = f"could not parse it ({type(exc).__name__})"
        if attempt < 5:
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

    if os.environ.get("CDP_TOKEN"):
        return os.environ["CDP_TOKEN"]

    raise TokenUnavailableError(
        f"No credentials for the model endpoint. Checked CAII_API_KEY, the workload token at "
        f"{JWT_FILE} ({last_detail}) and CDP_TOKEN. Inside Cloudera AI Workbench the token is "
        f"mounted automatically; for local runs set CAII_API_KEY or CDP_TOKEN in .env."
    )
