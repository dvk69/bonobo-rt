from importlib.metadata import entry_points

from bonobo.util.testing import all_runners


def test_entrypoint():
    commands = {ep.name: ep for ep in entry_points(group="bonobo.commands")}

    assert not {"convert", "init", "inspect", "run", "version"}.difference(set(commands))


@all_runners
def test_no_command(runner):
    _, err, exc = runner(catch_errors=True)
    assert type(exc) == SystemExit
    assert "error: the following arguments are required: command" in err
