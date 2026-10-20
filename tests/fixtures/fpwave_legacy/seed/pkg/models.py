"""Data models for the fixture package."""

from pydantic import BaseModel


class Item(BaseModel):
    """One catalogue item."""

    name: str
    price: float = 0.0


class Widget:
    """A widget with a mutable size."""

    def __init__(self, size: int = 1) -> None:
        self._size = size

    @property
    def size(self) -> int:
        """The widget size."""
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        self._size = value
