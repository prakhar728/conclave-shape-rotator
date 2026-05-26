from __future__ import annotations
"""
SkillCard — the self-declaration contract every skill must provide.

Each skill exports a SkillCard instance that declares:
- input_model:    Pydantic model for validating user submissions
- output_keys:    Guardrail whitelist — only these keys leave the pipeline
- trigger_modes:  How/when the pipeline runs (threshold, manual, instant)
- roles:          What admin vs user can do and see
- setup_prompt:   Text block for LLM-guided admin onboarding
- config:         Skill-specific defaults (thresholds, bounds, etc.)

Security note:
The analyze node's tools can read raw submission text inside the TEE.
Prompt injection defense relies on programmatic guardrails (guardrails.py)
— key whitelist, score clamping, leakage detection — not on keeping text
away from the LLM. If new tools expose raw text, update guardrails.py.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, Type

from pydantic import BaseModel


@dataclass
class SkillCard:
    name: str
    description: str
    run: Callable                        # the run_skill() entry point
    input_model: Type[BaseModel]         # Pydantic model for this skill's inputs
    output_keys: set                     # allowed output keys (mirrors ALLOWED_OUTPUT_KEYS)
    user_output_keys: set = field(default_factory=set)  # keys visible to user role (subset of output_keys)
    config: dict = field(default_factory=dict)          # skill-specific config params
    trigger_modes: list = field(default_factory=list)   # supported trigger declarations
    roles: dict = field(default_factory=dict)           # admin + user role declarations
    setup_prompt: str = ""                              # LLM onboarding text for admins (metadata/docs)
    user_display: dict = field(default_factory=dict)    # display hints per output key for the frontend renderer
    version: str = "0.1.0"

    def metadata(self) -> dict:
        """JSON-serializable card metadata for the /skills endpoint."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": self.input_model.model_json_schema(),
            "output_keys": sorted(self.output_keys),
            "user_output_keys": sorted(self.user_output_keys),
            "config": self.config,
            "trigger_modes": self.trigger_modes,
            "roles": self.roles,
            "setup_prompt": self.setup_prompt,
            "user_display": self.user_display,
        }
