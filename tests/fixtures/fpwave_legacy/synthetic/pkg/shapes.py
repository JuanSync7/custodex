"""Geometry shapes."""

from dataclasses import dataclass, field


@dataclass
class Point:
    """A 2-D point."""

    x: float
    y: float = 0.0
    tags: list[str] = field(default_factory=list)

    def norm(self) -> float:
        """Return the Euclidean norm."""
        return (self.x**2 + self.y**2) ** 0.5
