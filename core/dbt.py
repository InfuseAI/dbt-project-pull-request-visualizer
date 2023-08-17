import os

from ruamel import yaml

from core.utils import console, run_command, RunCommandException


def find_dbt_project(project_path: str):
    dbt_project_file = 'dbt_project.yml'

    dbt_project_dir = None
    for root, directory, files in os.walk(project_path):
        if dbt_project_file in files:
            dbt_project_dir = root

    if dbt_project_dir is None:
        return None

    return dbt_project_dir


def patch_dbt_profiles(dbt_project_dir: str):
    if os.path.exists(os.path.join(dbt_project_dir, 'profiles.yml')):
        console.print("[[bold yellow]WARNING[/bold yellow]] profiles.yml already exists, skip patching")
        return True

    with open(os.path.join(dbt_project_dir, 'dbt_project.yml'), 'r') as steam:
        dbt_project = yaml.load(steam, Loader=yaml.Loader)
        profile_name = dbt_project.get('profile', 'default')

        with open(os.path.join(dbt_project_dir, 'profiles.yml'), 'w') as fd:
            yaml.dump({
                profile_name: {
                    'target': 'dev',
                    'outputs': {
                        'dev': {
                            'type': 'duckdb',
                            'path': f'{dbt_project_dir}/{profile_name}.duckdb'
                        }
                    }
                }
            }, fd)
        console.print(f"patched dbt_project.yml with profile: {profile_name}")


def run_dbt_deps_command(dbt_project_path):
    cmd = ['dbt', 'deps', '--project-dir', dbt_project_path, '--profiles-dir', dbt_project_path]
    try:
        return run_command(cmd)
    except RunCommandException as e:
        e.msg = ("Failed to execute 'dbt deps'\n"
                 "Probably caused by private packages.")
        raise e


def run_dbt_parse_command(dbt_project_path):
    cmd = ['dbt', 'parse', '--project-dir', dbt_project_path, '--profiles-dir', dbt_project_path]
    try:
        return run_command(cmd)
    except RunCommandException as e:
        e.msg = ("Failed to execute 'dbt parse'\n"
                 "Probably caused by dbt version or no profile be filled in 'dbt_project.yml' file.")
        raise e
