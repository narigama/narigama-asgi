import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic
from typing import TypeVar


T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class Option(Generic[T]):
    # inner value of this option, never access it directly, instead using Option.get_value() or Option.get_value_or()
    _value: T | None = None

    def __repr__(self) -> str:
        if self.has_value():
            return "Option::Some({})".format(self._value)
        return "Option::None"

    def has_value(self) -> bool:
        """Check if the Option contains a value or not."""
        return self._value is not None

    def get_value(self) -> T:
        """Attempt to get value, raises ValueError if missing."""
        if not self.has_value():
            msg = "Option did not contain a value. Use Option.has_value() before attempting Option.get_value()."
            raise ValueError(msg)
        return self._value

    def get_value_or(self, default: U | Callable[[], U]) -> T | U:
        """Attempt to get a value, or return the provided default.

        The default may either be a value, or a fn() -> U"""
        if self.has_value():
            # we have a value, ignore the default
            return self._value

        # otherwise call the default if it's callable
        return default() if inspect.isfunction(default) else default

    def map_value(self, fn: Callable[[T], U]) -> "Option[U]":
        """Map Option[T] to Option[U] via the provided callable.

        This is eagerly evaluated and immediately applies the mapping."""
        value = None
        if self.has_value():
            value = fn(self._value)
        return self.__class__(value)
