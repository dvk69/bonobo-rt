import pytest

from bonobo.config.configurables import Configurable
from bonobo.config.options import Option
from bonobo.util.inspect import inspect_node


class NoOptConfigurable(Configurable):
    pass


class MyConfigurable(Configurable):
    required_str = Option(str)
    default_str = Option(str, default="foo")
    integer = Option(int, required=False)


class MyHarderConfigurable(MyConfigurable):
    also_required = Option(bool, required=True)


class MyBetterConfigurable(MyConfigurable):
    required_str = Option(str, required=False, default="kaboom")


class MyConfigurableUsingPositionalOptions(MyConfigurable):
    first = Option(str, required=True, positional=True)
    second = Option(str, required=True, positional=True)
    third = Option(str, required=False, positional=True)


def test_missing_required_option_error():
    with inspect_node(MyConfigurable()) as ni:
        assert ni.partial

    with pytest.raises(TypeError) as exc:
        MyConfigurable(_final=True)
    assert exc.match("missing 1 required option:")


def test_missing_required_options_error():
    with inspect_node(MyHarderConfigurable()) as ni:
        assert ni.partial

    with pytest.raises(TypeError) as exc:
        MyHarderConfigurable(_final=True)
    assert exc.match("missing 2 required options:")


def test_extraneous_option_error():
    with pytest.raises(TypeError) as exc:
        MyConfigurable(required_str="foo", hello="world")
    assert exc.match("got 1 unexpected option:")


def test_extraneous_options_error():
    with pytest.raises(TypeError) as exc:
        MyConfigurable(required_str="foo", hello="world", acme="corp")
    assert exc.match("got 2 unexpected options:")


def test_defaults():
    o = MyConfigurable(required_str="hello")

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.required_str == "hello"
    assert o.default_str == "foo"
    assert o.integer is None


def test_str_type_factory():
    o = MyConfigurable(required_str=42)

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.required_str == "42"
    assert o.default_str == "foo"
    assert o.integer is None


def test_int_type_factory():
    o = MyConfigurable(required_str="yo", default_str="bar", integer="42")

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.required_str == "yo"
    assert o.default_str == "bar"
    assert o.integer == 42


def test_bool_type_factory():
    o = MyHarderConfigurable(required_str="yes", also_required="True")

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.required_str == "yes"
    assert o.default_str == "foo"
    assert o.integer is None
    assert o.also_required is True


def test_option_resolution_order():
    o = MyBetterConfigurable()

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.required_str == "kaboom"
    assert o.default_str == "foo"
    assert o.integer is None


def test_option_positional():
    o = MyConfigurableUsingPositionalOptions("1", "2", "3", required_str="hello")

    with inspect_node(o) as ni:
        assert not ni.partial

    assert o.first == "1"
    assert o.second == "2"
    assert o.third == "3"
    assert o.required_str == "hello"
    assert o.default_str == "foo"
    assert o.integer is None


def test_no_opt_configurable():
    o = NoOptConfigurable()

    with inspect_node(o) as ni:
        assert not ni.partial


# ---------------------------------------------------------------------------
# PartiallyConfigured tests (2f)
# ---------------------------------------------------------------------------


def test_partially_configured_is_partial():
    """Missing required options return a PartiallyConfigured (functools.partial-like) instance."""
    import functools
    from bonobo.config.configurables import PartiallyConfigured

    p = MyConfigurable()
    assert isinstance(p, functools.partial)
    assert isinstance(p, PartiallyConfigured)


def test_partially_configured_options_values_keyword():
    """_options_values on a partial with keyword args reflects those kwargs."""
    p = MyConfigurable(default_str="bar")
    assert p._options_values.get("default_str") == "bar"
    # required_str was not given — should be absent or None
    assert "required_str" not in p._options_values or p._options_values["required_str"] is None


def test_partially_configured_options_values_positional():
    """_options_values on a partial with positional args maps them to field names."""
    p = MyConfigurableUsingPositionalOptions("alpha", required_str="hello")
    # 'first' is the first positional option — should appear in _options_values
    assert p._options_values.get("first") == "alpha"


def test_partially_configured_getattr_delegates_to_option():
    """__getattr__ on a PartiallyConfigured delegates unknown attrs to the option descriptor."""
    p = MyConfigurable(default_str="override")
    # Accessing the option via __getattr__ should return the Option object or its get result
    # (just verifying it doesn't raise AttributeError)
    val = p.default_str
    assert val == "override"


def test_partially_configured_getattr_missing_raises():
    """__getattr__ on a PartiallyConfigured raises AttributeError for unknown attrs."""
    p = MyConfigurable()
    with pytest.raises(AttributeError):
        _ = p.this_attribute_does_not_exist


def test_partially_configured_completes_to_full_instance():
    """Calling a PartiallyConfigured with the remaining options returns a real instance."""
    p = MyConfigurable()
    from bonobo.util.inspect import inspect_node

    with inspect_node(p) as ni:
        assert ni.partial

    full = p(required_str="hello")
    with inspect_node(full) as ni:
        assert not ni.partial

    assert full.required_str == "hello"
    assert full.default_str == "foo"


def test_partially_configured_c_extension_path():
    """PartiallyConfigured subclasses _functools.partial when available (Python 3.12+ C path)."""
    try:
        import _functools
        from bonobo.config.configurables import PartiallyConfigured

        assert issubclass(PartiallyConfigured, _functools.partial)
        p = MyConfigurable()
        # Verify the C-extension subclass works: .func, .args, .keywords all present
        assert p.func is MyConfigurable
        assert isinstance(p.args, tuple)
        assert isinstance(p.keywords, dict)
    except ImportError:
        pytest.skip("_functools C extension not available on this interpreter")
