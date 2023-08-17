import atexit
import os
import re
import shutil
import subprocess
import tempfile
from typing import List

from git import Repo
from github import Repository
from rich.console import Console

console = Console()


class RunCommandException(BaseException):
    def __init__(self, cmd: List[str], return_code: int, msg: str = None):
        self.cmd: List[str] = cmd
        self.return_code: int = return_code
        self.msg = msg
        super().__init__('Run command failed')


def parse_github_pr_url(url) -> (bool, str, int):
    # URL format "https://github.com/owner/reponame/pull/prID"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)/pull/(\d+)', url)
    if match:
        repo = match.group(1)
        pr_id = int(match.group(2))
        return True, repo, pr_id
    return False, '', None


def parse_github_url(url) -> (bool, str):
    # URL format "https://github.com/owner/reponame"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)', url)
    if match:
        repo = match.group(1)
        return True, repo
    return False, ''


def clone_github_repo(repo: Repository, auto_delete_clone_dir: bool = True) -> (Repo, str):
    tempdir = tempfile.mkdtemp()
    if auto_delete_clone_dir:
        atexit.register(shutil.rmtree, tempdir)
    git_repo = Repo.clone_from(repo.clone_url, tempdir)
    return git_repo, tempdir


def run_command(cmd, cwd=None, env=None):
    console.print(f"[Executing command] '{' '.join(cmd)}'")
    process = None
    outs = ''
    try:
        env = os.environ.copy().update(env) if env else os.environ.copy()
        process = subprocess.Popen(cmd,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   env=env,
                                   text=True,
                                   cwd=cwd)
        for line in iter(process.stdout.readline, ""):
            console.print(line, end="")
            outs += line
        return_code = process.wait()
    except BaseException as e:
        if process:
            process.kill()
            return_code = process.wait()
        else:
            return_code = 1

    if return_code != 0:
        console.print(f"[[bold red]Error[/bold red]] executing command:\n{outs}")
        raise RunCommandException(cmd, return_code)
    else:
        return outs
