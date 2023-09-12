import os

import click

import core.config
from core.analyzer import DbtProjectAnalyzer
from core.utils import RunCommandException


@click.command(name='dbt-project-visualizer', help='Visualize the GitHub Repo or Pull Request of your dbt projects')
@click.argument('github_url', required=True, type=str)
@click.option('--upload/--no-upload', default=False, help='Upload the report to PipeRider Cloud', required=False)
@click.option('--upload-project', default=None, help='PipeRider Cloud Project Name', required=False)
@click.option('--upload-token', default=None, help='PipeRider Cloud API Token', required=False)
@click.option('--debug/--no-debug', default=False, help='Enable debug mode', required=False)
@click.pass_context
def cli(ctx: click.Context, github_url: str, **kwargs):
    upload = kwargs.get('upload', False)
    upload_project = kwargs.get('upload_project') or os.getenv('PIPERIDER_CLOUD_PROJECT', None)
    upload_token = kwargs.get('upload_token') or os.getenv('PIPERIDER_CLOUD_PROJECT', None)
    core.config.DEBUG = kwargs.get('debug', False)

    if upload and (upload_project is None or upload_token is None):
        click.echo('Please specify --upload-project and --upload-token when using --upload option')
        click.echo(ctx.get_help())
        exit(1)

    try:
        analyzer = DbtProjectAnalyzer(github_url,
                                      upload=upload,
                                      share=True,
                                      project_name=upload_project,
                                      api_token=upload_token)
        analyzer.exec()
        analyzer.summary()
    except RunCommandException as e:
        click.echo(f'Failed to exec the project: {e.msg}')
        exit(e.return_code)


if __name__ == '__main__':
    cli()
