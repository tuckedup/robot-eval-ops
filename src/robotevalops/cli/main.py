"""CLI entrypoint (lead-owned). Sub-apps live in sibling modules owned by each worker:
  session_cmds.py (core)  robot_cmds.py (robotics)  data_cmds.py (data/storage)  report_cmds.py (eval)
Each module must expose `app = typer.Typer(...)`. `demo` is lead-owned (cli/demo_cmds.py)."""

from __future__ import annotations

import typer

from robotevalops import __version__
from robotevalops.cli import data_cmds, demo_cmds, report_cmds, robot_cmds, session_cmds

app = typer.Typer(
    help="RobotEvalOps: reproducible robot-policy evaluation and data QA.", no_args_is_help=True
)
app.add_typer(session_cmds.app, name="session")
app.add_typer(robot_cmds.app, name="robot")
app.add_typer(data_cmds.app, name="data")
app.add_typer(report_cmds.app, name="report")
app.add_typer(demo_cmds.app, name="demo")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
