import typer
from rich.console import Console
from rich.table import Table

from .distro import DistroInfo, detect_distro
from .commands.prepare import prepare
from .commands.validate import validate_command
from .commands.analyze import analyze


app = typer.Typer(help="Prepare and operate a Linux system for kdump analysis")
console = Console()


@app.command("detect")
def detect() -> None:
    info: DistroInfo = detect_distro()
    table = Table(title="Detected Distro")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("id", info.id)
    table.add_row("version_id", info.version_id or "")
    table.add_row("pretty_name", info.pretty_name or "")
    console.print(table)


app.command(name="prepare")(prepare)
app.command(name="validate")(validate_command)
app.command(name="analyze")(analyze)


if __name__ == "__main__":
    app()
