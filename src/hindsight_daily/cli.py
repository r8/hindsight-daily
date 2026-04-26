import click
from .config import config


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx, verbose):
    if verbose is not None:
        config.set({"verbose": verbose})
    ctx.obj = config


@cli.command()
def sync() -> None:
    print("Sync")
