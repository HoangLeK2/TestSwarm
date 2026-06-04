"""Extraction strategy registry (DF-T-06-006)."""
from __future__ import annotations

from typing import Any, Callable, Protocol

from services.content.extraction.hierarchy.parser import HierarchyNode
from services.content.extraction.models import StrategyNotFoundError


class ExtractionStrategy(Protocol):
    name: str

    def extract(self, root: HierarchyNode, config: dict[str, Any]) -> tuple[list[dict[str, Any]] | dict[str, Any], dict[str, Any]]: ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, ExtractionStrategy] = {}

    def register(self, strategy: ExtractionStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def register_fn(self, name: str, fn: Callable[[HierarchyNode, dict[str, Any]], tuple[Any, dict]]) -> None:
        class _FnStrategy:
            def __init__(self) -> None:
                self.name = name

            def extract(self, root: HierarchyNode, config: dict[str, Any]):
                return fn(root, config)

        self.register(_FnStrategy())

    def get(self, name: str) -> ExtractionStrategy:
        strategy = self._strategies.get(name)
        if strategy is None:
            raise StrategyNotFoundError(name, available=sorted(self._strategies))
        return strategy

    def list_names(self) -> list[str]:
        return sorted(self._strategies)


_registry = StrategyRegistry()


def get_strategy_registry() -> StrategyRegistry:
    return _registry
