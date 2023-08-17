import pytest
from narigama_asgi.option import Option


def test_option_with_none():
    result = Option()
    assert result._value is None
    assert result.has_value() is False


def test_option_with_value():
    result = Option(42)
    assert result._value is 42
    assert result.has_value() is True


def test_option_get_value():
    # try without
    option = Option()
    with pytest.raises(ValueError) as ex:
        assert option.get_value()
        msg = "Option did not contain a value. Use Option.has_value() before attempting Option.get_value()."
        assert str(ex.value) == msg

    # try with
    assert Option(42).get_value() == 42


def test_option_get_value_or_constant_with_none():
    assert Option().get_value_or(42) == 42


def test_option_get_value_or_constant_with_value():
    assert Option(10).get_value_or(42) == 10


def test_option_get_value_or_with_callable_with_none():
    fn = lambda: 42
    assert Option().get_value_or(fn) == 42


def test_option_get_value_or_with_callable_with_value():
    fn = lambda: 42
    assert Option(10).get_value_or(fn) == 10


def test_option_map_value_with_none():
    fn = lambda x: x**2
    assert Option().map_value(fn) == Option()


def test_option_map_value_with_some():
    fn = lambda x: x**2
    assert Option(42).map_value(fn) == Option(1764)
