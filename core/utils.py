import atexit
import os
import re
import shutil
import subprocess
import tempfile
from enum import Enum
from typing import List, Tuple, Optional
from urllib.parse import urlparse

from git import Repo
from github import Repository
from github.Auth import Token
from rich.console import Console

console = Console()


class AnalysisType(Enum):
    UNKNOWN = ''
    REPOSITORY = 'repository'
    PULL_REQUEST = 'pull-request'


class RunCommandException(BaseException):
    def __init__(self, cmd: List[str], return_code: int, msg: str = None):
        self.cmd: List[str] = cmd
        self.return_code: int = return_code
        self.msg = msg
        super().__init__('Run command failed')


def parse_github_pr_url(url) -> Tuple[bool, str, int | None]:
    # URL format "https://github.com/owner/reponame/pull/prID"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)/pull/(\d+)', url)
    if match:
        repo = match.group(1)
        pr_id = int(match.group(2))
        return True, repo, pr_id
    return False, '', None


def parse_github_repo_url(url) -> Tuple[bool, str]:
    # URL format "https://github.com/owner/reponame"
    match = re.search(r'https://github\.com/([^/]+/[^/]+)', url)
    if match:
        repo = match.group(1)
        return True, repo
    return False, ''


def parse_github_url(url: str) -> Tuple[AnalysisType, int, str]:
    ret, repo_name, pr_id = parse_github_pr_url(url)
    if ret is False:
        ret, repo_name = parse_github_repo_url(url)
        if ret is False:
            # Invalid GitHub URL
            raise Exception(f"Invalid GitHub URL: {url}")
        else:
            analysis_type = AnalysisType.REPOSITORY
    else:
        analysis_type = AnalysisType.PULL_REQUEST
    return analysis_type, pr_id, repo_name


def clone_github_repo(repo: Repository, auth: Optional[Token], auto_delete_clone_dir: bool = True) -> Tuple[Repo, str]:
    tempdir = tempfile.mkdtemp()
    if auto_delete_clone_dir:
        atexit.register(shutil.rmtree, tempdir)

    if auth is None:
        git_repo = Repo.clone_from(repo.clone_url, tempdir)
    else:
        parsed_url = urlparse(repo.clone_url)
        url = f'{parsed_url.scheme}://{auth.token}@{parsed_url.hostname}{parsed_url.path}'
        git_repo = Repo.clone_from(url, tempdir)
    return git_repo, tempdir


def run_command(cmd, cwd=None, env=None):
    console.print(f"[Executing command] '{' '.join(cmd)}'")
    process = None
    outs = ''
    try:
        env_copy = os.environ.copy()
        if env:
            env_copy.update(env)
        process = subprocess.Popen(cmd,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   env=env_copy,
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
