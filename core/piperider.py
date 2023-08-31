from core.utils import run_command


def piperider_run_command(dbt_project_dir: str, options: dict = None):
    cmd = ['piperider', 'run', '--skip-datasource', '--dbt-project-dir', dbt_project_dir, '--dbt-profiles-dir',
           dbt_project_dir]
    extra_env = None
    if options:
        if options.get('output'):
            cmd += ['-o', options['output']]
        if options.get('upload_project'):
            cmd += ['--upload', '--share', '--project', options['upload_project']]
        if options.get('api_token'):
            extra_env = {'PIPERIDER_API_TOKEN': options['api_token']}
    return run_command(cmd, env=extra_env)


def piperider_compare_reports_command(dbt_project_path, result_path, options: dict = None):
    cmd = ['piperider', 'compare-reports', '--last', '-o', result_path, '--debug']
    extra_env = None
    if options:
        if options.get('upload_project'):
            cmd += ['--upload', '--share', '--project', options['upload_project']]
        if options.get('api_token'):
            extra_env = {'PIPERIDER_API_TOKEN': options['api_token']}
    return run_command(cmd, cwd=dbt_project_path, env=extra_env)
