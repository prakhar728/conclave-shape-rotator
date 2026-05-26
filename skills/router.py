from __future__ import annotations
from typing import Callable, Any

from pydantic import BaseModel


class SkillRouter:
    def __init__(self):
        self._registry: dict = {}   # name -> SkillCard

    def register(self, name_or_card, fn: Callable = None) -> None:
        """Register a skill.

        Accepts either:
          register(skill_card)          — preferred, full metadata
          register("name", callable)    — legacy, wraps in a minimal SkillCard
        """
        from core.skill_card import SkillCard
        if isinstance(name_or_card, SkillCard):
            self._registry[name_or_card.name] = name_or_card
        else:
            # Legacy path — used by tests and simple registrations
            card = SkillCard(
                name=name_or_card,
                description="",
                run=fn,
                input_model=BaseModel,
                output_keys=set(),
            )
            self._registry[name_or_card] = card

    def list_skills(self) -> list[str]:
        return list(self._registry.keys())

    def list_cards(self) -> list[dict]:
        """Return rich metadata for every registered skill."""
        return [card.metadata() for card in self._registry.values()]

    def get_card(self, name: str):
        if name not in self._registry:
            raise KeyError(f"Skill '{name}' is not registered. Available: {self.list_skills()}")
        return self._registry[name]

    def invoke(self, skill_name: str, **kwargs) -> Any:
        card = self.get_card(skill_name)
        return card.run(**kwargs)
