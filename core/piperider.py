import os

from core.utils import run_command


def piperider_run(dbt_project_dir: str, options: dict = None):
    cmd = ['piperider', 'run', '--skip-datasource', '--dbt-project-dir', dbt_project_dir,
           '--dbt-profiles-dir',
           dbt_project_dir]
    extra_env = {}
    if options:
        if options.get('output'):
            cmd += ['-o', options['output']]
        if options.get('upload_project'):
            cmd += ['--upload', '--project', options['upload_project']]
        if options.get('share'):
            cmd += ['--share']
        if options.get('api_token'):
            extra_env = {'PIPERIDER_API_TOKEN': options['api_token']}
    if os.environ.get('PIPERIDER_API_SERVICE'):
        extra_env['PIPERIDER_API_SERVICE'] = os.environ.get('PIPERIDER_API_SERVICE')
    return run_command(cmd, env=extra_env)


def piperider_compare_reports(dbt_project_path, result_path, options: dict = None):
    cmd = ['piperider', 'compare-reports', '--last', '-o', result_path]
    extra_env = {}
    if options:
        if options.get('upload_project'):
            cmd += ['--upload', '--project', options['upload_project']]
        if options.get('share'):
            cmd += ['--share']
        if options.get('api_token'):
            extra_env = {'PIPERIDER_API_TOKEN': options['api_token']}
    if os.environ.get('PIPERIDER_API_SERVICE'):
        extra_env['PIPERIDER_API_SERVICE'] = os.environ.get('PIPERIDER_API_SERVICE')
    return run_command(cmd, cwd=dbt_project_path, env=extra_env)
