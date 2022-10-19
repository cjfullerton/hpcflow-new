import click
import zarr


@click.group()
@click.version_option(prog_name="hpcflow", version="0.2.0a4")
def cli():
    pass


@cli.command()
def hello():
    click.echo("Hello hello")


@cli.group()
def config():
    """Configuration sub-command for getting and setting data in the configuration
    file(s)."""


@config.command()
@click.option("--all", is_flag=True)
def get(all):
    """Show the value of the specified configuration item."""
    click.echo("hello get --all")


if __name__ == "__main__":
    zarr.array([1, 2, 3])
    cli()
