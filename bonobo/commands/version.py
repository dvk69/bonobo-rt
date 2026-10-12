from mondrian import humanizer

from bonobo.commands import BaseCommand


def get_versions(*, all=False, quiet=None):
    import bonobo
    from bonobo.util.pkgs import bonobo_packages

    yield _format_version("bonobo", bonobo.__version__, quiet=quiet)

    if all:
        for name in sorted(bonobo_packages):
            if name != "bonobo":
                try:
                    mod_name = name.replace("-", "_")
                    mod = __import__(mod_name)
                    try:
                        yield _format_version(name, mod.__version__, quiet=quiet)
                    except Exception as exc:
                        yield "{} ({})".format(name, exc)
                except ImportError as exc:
                    yield "{} is not importable ({}).".format(name, exc)


class VersionCommand(BaseCommand):
    @humanizer.humanize()
    def handle(self, *, all=False, quiet=False):
        for line in get_versions(all=all, quiet=quiet):
            print(line)

    def add_arguments(self, parser):
        parser.add_argument("--all", "-a", action="store_true")
        parser.add_argument("--quiet", "-q", action="count")


def _format_version(name, ver, *, quiet=False):
    from bonobo.util.pkgs import bonobo_packages

    dist = bonobo_packages.get(name)
    location = str(dist.locate_file(".")) if dist is not None else "unknown"

    args = {"name": name, "version": ver, "location": location}

    if not quiet:
        return "{name} v.{version} (in {location})".format(**args)
    if quiet < 2:
        return "{name} {version}".format(**args)
    if quiet < 3:
        return "{version}".format(**args)

    raise RuntimeError("Hard to be so quiet...")
