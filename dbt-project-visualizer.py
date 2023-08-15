#! /usr/bin/env python3
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from git import Repo
from github import Auth, Github, Repository
from rich.console import Console
from ruamel import yaml

GITHUB_API_TOKEN = os.environ.get('GITHUB_API_TOKEN', '')


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
        return True

    with open(os.path.join(dbt_project_dir, 'dbt_project.yml'), 'r') as steam:
        dbt_project = yaml.load(steam, Loader=yaml.Loader)
        console = Console()
        console.print(dbt_project)
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


def run_dbt_command(dbt_project_dir: str, command):
    console = Console()
    cmd = ['dbt', command, '--project-dir', dbt_project_dir, '--profiles-dir', dbt_project_dir]
    console.rule(f"Running dbt command: 'dbt {command}'")

    # Execute the command
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Check if the command was successful
    if result.returncode != 0:
        console.print(f"Error executing dbt command:\n{result.stdout}")
    else:
        console.print(result.stdout)


def run_piperider_command(dbt_project_dir: str, command, options: dict = None):
    console = Console()
    cmd = ['piperider', command, '--dbt-project-dir', dbt_project_dir, '--dbt-profiles-dir', dbt_project_dir]

    if command == 'run' and options and 'output' in options:
        cmd += ['-o', options['output']]
    console.rule(f"Running piperider command: 'piperider {command}'")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"Error executing dbt command:\n{result.stdout}")
    else:
        console.print(result.stdout)


def parse_dbt_manifest(dbt_project_dir: str):
    with open(os.path.join(dbt_project_dir, 'target', 'manifest.json'), 'r') as steam:
        manifest = json.load(steam)
        console = Console()
        console.print(manifest)


def compare_piperider_run(project_path, result_path):
    console = Console()
    cmd = ['piperider', 'compare-reports', '--last', '-o', result_path]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_path)
    if result.returncode != 0:
        console.print(f"Error executing dbt command:\n{result.stdout}")
    else:
        console.print(result.stdout)


def generate_piperider_report(branch, project_path, repo):
    console = Console()
    dbt_project_path = find_dbt_project(project_path)
    if dbt_project_path is None:
        console.print("dbt project not found")
        exit(1)
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
    console = Console()
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
    if GITHUB_API_TOKEN:
        auth = Auth.Token(GITHUB_API_TOKEN)

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
    git_repo.git.checkout(base_branch)
    generate_piperider_report(base_branch, project_path, repo)

    if head_branch:
        console.rule(f"Process Head Branch: '{head_branch}'")
        git_repo.git.checkout(head_branch)
        generate_piperider_report(head_branch, project_path, repo)

        console.rule(f"Compare '{head_branch}' vs '{base_branch}'")
        compare_result_path = os.path.join('results', repo.full_name, f'{head_branch}_vs_{base_branch}')
        os.makedirs(compare_result_path, exist_ok=True)
        compare_piperider_run(project_path, os.path.abspath(compare_result_path))


if __name__ == '__main__':
    main()
