import dataclasses
import datetime
import os


def now(precise=False) -> datetime.datetime:
    """Return a localised timestamp."""
    timestamp = datetime.datetime.now(datetime.UTC)
    if not precise:
        timestamp = timestamp.replace(microsecond=0)
    return timestamp


def env(key, convert=str, **kwargs):
    """
    A factory around `dataclasses.field` that can be used to load or default
    an envvar. If you wish to load from an external source, do that first and
    inject it's keys/values into os.environ before instantiating your
    dataclass.

    Args:
        key: in the format of either KEY or KEY:DEFAULT
        convert: a function that accepts a string and returns a different type
        kwargs: any kwargs to be passed to `dataclasses.field`

    Returns:
        dataclasses.field

    Raises:
        KeyError: in the event an envvar isn't found and doesn't have a default
    """
    key, partition, default = key.partition(":")

    def default_factory(key=key, default=default, convert=convert):
        # the key is missing
        if key not in os.environ:
            # So was the partition: This is a mandatory field and it didn't provide a default.
            if not partition:
                raise KeyError(key)
            # Use anything after the partition, even an empty string.
            return convert(default)
        return convert(os.environ[key])

    return dataclasses.field(default_factory=default_factory, **kwargs)
