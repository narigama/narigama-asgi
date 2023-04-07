import dataclasses
import datetime
import os


def now(precise=False) -> datetime.datetime:
    """Return a localised timestamp."""
    ts = datetime.datetime.now(datetime.timezone.utc).astimezone()
    if not precise:
        ts = ts.replace(microsecond=0)
    return ts


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
        if key in os.environ:
            return convert(os.environ[key])
        else:
            # if a partition was detected use anything after it, even an empty string
            if partition == ":":
                return convert(default)
            else:
                raise KeyError(key)

    return dataclasses.field(default_factory=default_factory, **kwargs)
