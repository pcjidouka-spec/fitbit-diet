import click


@click.group(invoke_without_command=True)
@click.pass_context
def app(ctx: click.Context) -> None:
    """Personal diet tracking CLI."""
    if ctx.invoked_subcommand is None:
        # 引数なし: デフォルト対話フローへ (Task 6.8 で本実装)
        click.echo("orchestrator not yet implemented")
