#! /usr/bin/env python3
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import List

from git import Repo
from github import Auth, Github, Repository
from rich.console import Console
from ruamel import yaml

console = Console()
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
PIPERIDER_API_TOKEN = os.environ.get('PIPERIDER_API_TOKEN')
PIPERIDER_CLOUD_PROJECT = os.environ.get('PIPERIDER_CLOUD_PROJECT')


def print_error(msg):
    print(msg, file=sys.stderr)


def usage():
    argv = sys.argv
    print_error(f"Usage: {argv[0]} <github-pull-request-url | github-repo-url>")


def parse_github_pr_url(url) -> (bool, str, int):
    # URL format "https://github.com/owner/reponame/pull/prID"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)/pull/(\d+)', url)
    if match:
        repo = match.group(1)
        pr_id = int(match.group(2))
        return True, repo, pr_id
    return False, "", None


def parse_github_url(url) -> (bool, str):
    # URL format "https://github.com/owner/reponame"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)', url)
    if match:
        repo = match.group(1)
        return True, repo


def clone_repo(repo: Repository) -> (Repo, str):
    tempdir = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, tempdir)
    git_repo = Repo.clone_from(repo.clone_url, tempdir)
    return git_repo, tempdir


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


class RunCommandException(BaseException):
    def __init__(self, cmd: List[str], return_code: int, msg: str = None):
        self.cmd: List[str] = cmd
        self.return_code: int = return_code
        self.msg = msg
        super().__init__('Run command failed')


def run_command(cmd, cwd=None):
    console.print(f"[Executing command] '{' '.join(cmd)}'")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        console.print(f"[[bold red]Error[/bold red]] executing command:\n{result.stdout}")
        raise RunCommandException(cmd, result.returncode)
    else:
        console.print(result.stdout)
        return 0


def run_dbt_command(dbt_project_dir: str, command):
    cmd = ['dbt', command, '--project-dir', dbt_project_dir, '--profiles-dir', dbt_project_dir]
    try:
        return run_command(cmd)
    except RunCommandException as e:
        if command == 'deps':
            e.msg = ("Failed to execute 'dbt deps'\n"
                     "Probably caused by private packages.")
        if command == 'parse':
            e.msg = ("Failed to execute 'dbt parse'\n"
                     "Probably caused by dbt version or no profile be filled in 'dbt_project.yml' file.")
        raise e


def run_piperider_command(dbt_project_dir: str, command, options: dict = None):
    cmd = ['piperider', command, '--dbt-project-dir', dbt_project_dir, '--dbt-profiles-dir', dbt_project_dir]
    if command == 'run' and options and 'output' in options:
        cmd += ['-o', options['output']]
    return run_command(cmd)


def compare_piperider_run(project_path, result_path, upload_project: str = None):
    cmd = ['piperider', 'compare-reports', '--last', '-o', result_path]
    if upload_project:
        cmd += ['--upload', '--share', '--project', upload_project]
    return run_command(cmd, cwd=project_path)


def generate_piperider_report(branch, project_path, repo):
    dbt_project_path = find_dbt_project(project_path)
    if dbt_project_path is None:
        raise Exception("dbt project not found")
    console.print(f"dbt project path: {dbt_project_path}")
    patch_dbt_profiles(dbt_project_path)
    run_dbt_command(dbt_project_path, 'deps')
    run_dbt_command(dbt_project_path, 'parse')
    piperider_output_dir = os.path.join('results', repo.full_name, branch)
    os.makedirs(piperider_output_dir, exist_ok=True)
    run_piperider_command(dbt_project_path, 'run',
                          {'output': piperider_output_dir})
    console.print(f'PipeRider Report: {os.path.abspath(os.path.join(piperider_output_dir, "index.html"))}')


def main():
    argv = sys.argv
    if len(argv) != 2:
        usage()
        return 1
    github_pr_url = argv[1]
    ret, repo, pr_id = parse_github_pr_url(github_pr_url)
    if ret is False:
        ret, repo = parse_github_url(github_pr_url)
        if ret is False:
            usage()
            return 1

    auth = None
    if GITHUB_TOKEN:
        auth = Auth.Token(GITHUB_TOKEN)

    gh = Github(auth=auth)

    repo = gh.get_repo(repo)
    git_repo, project_path = clone_repo(repo)
    base_branch = repo.default_branch
    head_branch = None

    console.print(f"GitHub repo: {repo.full_name}")
    console.print(f"Project path: {project_path}")

    if pr_id:
        pr = repo.get_pull(pr_id)
        base_branch = pr.base.ref
        head_branch = pr.head.ref
        console.print(f"PR: {pr.title} #{pr.number}")
        console.print(f"Author: {pr.user.name} @{pr.user.login}")
        console.print(f"URL: {pr.html_url}")
        console.print(f"State: {pr.state}")

    console.rule(f"Process Base Branch: '{base_branch}'")
    try:
        git_repo.git.checkout(base_branch)
        generate_piperider_report(base_branch, project_path, repo)

        if head_branch:
            console.rule(f"Process Head Branch: '{head_branch}'")
            git_repo.git.checkout(head_branch)
            generate_piperider_report(head_branch, project_path, repo)

            console.rule(f"Compare '{head_branch}' vs '{base_branch}'")
            compare_result_path = os.path.join('results', repo.full_name, f'{head_branch}_vs_{base_branch}')
            os.makedirs(compare_result_path, exist_ok=True)

            if PIPERIDER_API_TOKEN and PIPERIDER_CLOUD_PROJECT:
                compare_piperider_run(project_path, os.path.abspath(compare_result_path), PIPERIDER_CLOUD_PROJECT)
            else:
                compare_piperider_run(project_path, os.path.abspath(compare_result_path))
    except RunCommandException as e:
        if e.msg:
            console.print(f"[[bold red]Error[/bold red]]: {e.msg}")
        else:
            console.print(
                f"[[bold red]Error[/bold red]]: Failed to execute CMD: '{' '.join(e.cmd[:2])}'")
        exit(e.return_code)
    except Exception as e:
        console.print(f"[[bold red]Error[/bold red]]: {e}")
        exit(1)


if __name__ == '__main__':
    main()
