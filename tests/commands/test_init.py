import os

import pytest

from bonobo.commands.init import InitCommand
from bonobo.util.testing import all_runners


@all_runners
def test_init_file(runner, tmpdir):
    target = tmpdir.join("foo.py")
    target_filename = str(target)
    runner("init", target_filename)
    assert os.path.exists(target_filename)

    out, err = runner("run", target_filename)
    assert out.replace("\n", " ").strip() == "Hello World"
    assert not err


@all_runners
@pytest.mark.parametrize("template", InitCommand.TEMPLATES)
def test_init_file_templates(runner, template, tmpdir):
    target = tmpdir.join("foo.py")
    target_filename = str(target)
    runner("init", target_filename)
    assert os.path.exists(target_filename)
    out, err = runner("run", target_filename)
    assert not err


# ---------------------------------------------------------------------------
# Jinja2 3.x regression tests (2d)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", InitCommand.TEMPLATES)
def test_template_renders_valid_python_source(tmpdir, template):
    """Generated files must be parseable Python (no jinja2 syntax leaking out)."""
    import ast

    cmd = InitCommand()
    target = str(tmpdir.join("out.py"))
    cmd.create_file_from_template(template=template, filename=target)

    with open(target) as f:
        source = f.read()

    # Must compile without SyntaxError
    ast.parse(source)


@pytest.mark.parametrize("template", InitCommand.TEMPLATES)
def test_template_trailing_newline(tmpdir, template):
    """Generated files must end with a newline (keep_trailing_newline=True)."""
    cmd = InitCommand()
    target = str(tmpdir.join("out.py"))
    cmd.create_file_from_template(template=template, filename=target)

    with open(target) as f:
        source = f.read()

    assert source.endswith("\n"), "Generated file must end with a trailing newline"


def test_template_no_html_escaping(tmpdir):
    """autoescape=False: angle-bracket strings in template vars must not be escaped."""
    # The 'name' variable is rendered literally; if autoescape were True,
    # characters like < > & would be escaped as &lt; &gt; &amp;.
    # We synthesise a custom loader with a template that echoes the name var.
    from jinja2 import Environment, DictLoader

    env = Environment(
        loader=DictLoader({"test.py-tpl": "# {{ name }}\n"}),
        autoescape=False,
        keep_trailing_newline=True,
    )
    result = env.get_template("test.py-tpl").render(name="a<b>c")
    assert result == "# a<b>c\n", f"Unexpected escaping: {result!r}"
