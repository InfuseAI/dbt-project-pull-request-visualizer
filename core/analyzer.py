import os
import re
import tempfile
from abc import ABCMeta, abstractmethod
from typing import List, Optional, Tuple, Union

from github import Github
from github.Auth import Token
from github.PullRequest import PullRequest
from github.Repository import Repository

import core.config
from core.dbt import dbt_deps, dbt_parse, find_dbt_projects, patch_dbt_profiles
from core.piperider import piperider_run, piperider_compare_reports
from core.utils import clone_github_repo, console, AnalysisType, parse_github_url


class EnvContext(object):
    def __init__(self, envs: dict, **kwargs):
        self.envs = envs or kwargs
        self.existing_envs = {}

    def __enter__(self):
        for k, v in self.envs.items():
            if k in os.environ:
                self.existing_envs[k] = os.environ[k]
            console.print('[Debug] Set environment variable: ', k, v) if core.config.DEBUG else None
            os.environ[k] = str(v)

    def __exit__(self, exc_type, exc_val, exc_tb):
        for k in self.envs.keys():
            if self.existing_envs.get(k):
                os.environ[k] = self.existing_envs[k]
            else:
                console.print('[Debug] Unset environment variable: ', k) if core.config.DEBUG else None
                del os.environ[k]


class AnalyzerResult(object):
    def __init__(self, name: str, path: str, url: str = None):
        self.name = name
        self.path = path
        self.url = AnalyzerResult.patch_utm_source(url, 'dbt_analyzer')

    @staticmethod
    def patch_utm_source(url: str, utm_source: str):
        if url is None:
            return None
        regex_rule = r'(?<=\?utm_source=)[^&]+'
        replaced_url = re.sub(regex_rule, utm_source, url)
        return replaced_url

    @property
    def report(self):
        path = self.path if os.path.isabs(self.path) else os.path.abspath(self.path)
        return self.url or path


def _output_result_path(*args):
    if os.access(os.path.curdir, os.W_OK):
        return os.path.join('results', *args)

    tempdir = tempfile.mkdtemp()
    return os.path.join(tempdir, *args)


class AnalyzerEventHandler(metaclass=ABCMeta):
    progress: int = 0

    @abstractmethod
    def handle_run_start(self):
        raise NotImplementedError

    @abstractmethod
    def handle_run_end(self):
        raise NotImplementedError

    @abstractmethod
    def handle_run_progress(self, msg, progress: int = None):
        raise NotImplementedError

    @abstractmethod
    def handle_run_error(self, error):
        raise NotImplementedError


class DefaultEventHandler(AnalyzerEventHandler):
    def handle_run_start(self):
        self.progress = 0
        pass

    def handle_run_end(self):
        self.progress = 100
        console.rule(f'{self.progress}% - Completed')

    def handle_run_progress(self, msg, progress: int = None):
        if progress is not None:
            self.progress = progress
        console.rule(f'{self.progress}% - {msg}')

    def handle_run_error(self, error):
        console.rule(error, style='bold red')


class DbtProjectAnalyzer(object):
    def __init__(self, url: str,
                 api_token: str = None,
                 dbt_project_path: str = None,
                 project_name: str = None,
                 upload: bool = False,
                 share: bool = False,
                 enable_quick_look_share: bool = True):
        self.url = url
        self.event_handler: AnalyzerEventHandler = DefaultEventHandler()

        github_token = os.environ.get('GITHUB_TOKEN', '')

        if enable_quick_look_share:
            os.environ['PIPERIDER_ENABLE_QUICK_LOOK_SHARE'] = 'true'

        auth = None
        if github_token:
            auth = Token(github_token)

        self.auth = auth
        self.github = Github(auth=auth)

        # Github
        self.repository = None
        self.pull_request = None
        self.analyze_type: AnalysisType = AnalysisType.UNKNOWN

        # Git
        self.git_repo = None
        self.base_branch = None
        self.base_sha = None
        self.head_branch = None
        self.head_sha = None
        self.project_path = None

        # Dbt
        self.dbt_project_path: Optional[str] = dbt_project_path
        self.dbt_project_paths: List[str] = []
        if self.dbt_project_path:
            self.dbt_project_paths = [self.dbt_project_path]

        # Control
        self.upload = upload
        self.share = share
        self.project_name = project_name
        self.api_token = api_token

        # Analyze Results
        self.result: AnalyzerResult | None = None
        self.base_result: AnalyzerResult | None = None  # Used for PR
        self.head_result: AnalyzerResult | None = None  # Used for PR

    def set_event_handler(self, event_handler: AnalyzerEventHandler):
        if event_handler and isinstance(event_handler, AnalyzerEventHandler):
            self.event_handler = event_handler
        else:
            raise Exception('Invalid event handler')

    def verify_github_url(self, url) -> Tuple[AnalysisType, Repository, PullRequest]:
        analysis_type, pr_id, repo_name = parse_github_url(url)

        # Fetch GitHub repository
        repository = self.github.get_repo(repo_name)
        if repository is None:
            # Unable access GitHub repository
            raise Exception(f"Unable access GitHub repository: {repo_name}")

        if pr_id:
            pull_request = repository.get_pull(pr_id)
            if pull_request is None:
                # Unable access GitHub pull request
                raise Exception(f"Unable access GitHub pull request: {pr_id}")
        else:
            pull_request = None

        return analysis_type, repository, pull_request

    def load_github_url(self) -> bool:
        self.analyze_type, self.repository, self.pull_request = self.verify_github_url(self.url)

        # Clone git repo
        self.event_handler.handle_run_progress('Cloning Git Repository', progress=1)
        self.git_repo, self.project_path = clone_github_repo(self.repository, self.auth)
        if self.dbt_project_path is None:
            self.dbt_project_paths = find_dbt_projects(self.project_path)
        else:
            self.dbt_project_paths = [os.path.join(self.project_path, self.dbt_project_path)]

        if self.analyze_type == AnalysisType.PULL_REQUEST:
            self.base_branch = self.pull_request.base.ref
            self.base_sha = self.pull_request.base.sha
            self.head_branch = self.pull_request.head.ref
            self.head_sha = self.pull_request.head.sha

            # Handle cross-repository pull request
            if self.pull_request.base.repo.full_name != self.pull_request.head.repo.full_name:
                self.git_repo.create_remote('head', self.pull_request.head.repo.clone_url)
                self.git_repo.git.fetch('head')
        else:
            self.base_branch = self.repository.default_branch

        return True

    def generate_piperider_report(self, branch_or_commit) -> Tuple[str, str]:
        self.git_repo.git.checkout(branch_or_commit)
        if self.dbt_project_path is None:
            raise Exception("Failed to find dbt_project.yml")

        patch_dbt_profiles(self.dbt_project_path)

        self.event_handler.handle_run_progress('Running dbt deps')
        dbt_deps(self.dbt_project_path)

        self.event_handler.handle_run_progress('Running dbt parse')
        dbt_parse(self.dbt_project_path)

        piperider_output_path = _output_result_path(self.repository.full_name, branch_or_commit)
        os.makedirs(piperider_output_path, exist_ok=True)
        options = {
            'output': os.path.abspath(piperider_output_path)
        }

        if self.upload:
            options['api_token'] = self.api_token
            options['upload_project'] = self.project_name
        if self.share:
            options['share'] = True

        self.event_handler.handle_run_progress('Running piperider')
        console_output = piperider_run(self.dbt_project_path, options=options)

        report_url = None
        if self.upload or self.share:
            match = re.search(r'Report #.* URL: (\S+)\n', console_output)
            if match:
                report_url = match.group(1)

        report_path = os.path.join(piperider_output_path, 'index.html')
        console.print(f'PipeRider Report: {report_path}')

        return report_path, report_url

    def compare_piperider_reports(self) -> Tuple[str, str]:
        compare_output_path = _output_result_path(self.repository.full_name,
                                                  f'{self.head_branch}_vs_{self.base_branch}')
        os.makedirs(compare_output_path, exist_ok=True)

        # Compare the latest 2 reports
        options = {}

        # Pre-compare
        if self.upload:
            options['api_token'] = self.api_token
            options['upload_project'] = self.project_name
        if self.share:
            options['share'] = True
        console_output = piperider_compare_reports(self.dbt_project_path, os.path.abspath(compare_output_path),
                                                   options=options)
        # Post-compare
        report_url = None
        if self.upload or self.share:
            match = re.search(r'Comparison report URL: (\S+)\n', console_output)
            if match:
                report_url = match.group(1)

        report_path = os.path.join(compare_output_path, 'index.html')
        return report_path, report_url

    def summary(self):
        if self.analyze_type == AnalysisType.PULL_REQUEST:
            summary, panel_width = self.summary_pull_request()
        elif self.analyze_type == AnalysisType.REPOSITORY:
            summary, panel_width = self.summary_repository()
        else:
            raise Exception(f"Unknown analyze type: {self.analyze_type}")

        from rich.markdown import Markdown
        from rich.panel import Panel

        panel = Panel(Markdown(summary), width=panel_width, expand=False)
        console.print(panel)
        if os.getenv('GITHUB_ACTIONS') == 'true':
            with open('summary.md', 'w') as f:
                f.write(summary)

    def summary_repository(self):
        # Repo summary
        panel_width = len(self.result.report) + 8
        content = f'''
# Dbt Project '{self.repository.full_name}' Repository Summary
- Repo URL: {self.repository.html_url}

## Default Branch - {self.repository.default_branch}
- Report: {self.result.report}
'''

        return content, panel_width

    def summary_pull_request(self):
        # PR summary
        base_report = self.base_result.report
        head_report = self.head_result.report
        compare_report = self.result.report
        panel_width = max(len(base_report), len(head_report), len(compare_report)) + 8
        content = f'''
# Dbt Project '{self.repository.full_name}' Pull Request #{self.pull_request.number} Summary
- Repo URL: {self.repository.html_url}
- PR URL: {self.pull_request.html_url}
- PR Title: {self.pull_request.title}
- PR Status: {self.pull_request.state}

## Pull Request - {self.pull_request.base.ref} <- {self.pull_request.head.ref} #{self.pull_request.number}
- Compare Report: {self.result.report}

### Base Branch - {self.pull_request.base.ref} {self.pull_request.base.sha[0:7]}
- Report: {base_report}

### Head Branch - {self.pull_request.head.ref} {self.pull_request.head.sha[0:7]}
- Report: {head_report}
'''
        return content, panel_width

    def pre_exec(self):
        if self.load_github_url() is False:
            raise Exception(f"Failed to load github url: {self.url}")

    def exec(self):
        if not self.dbt_project_paths:
            return

        # Get next job
        self.dbt_project_path = self.dbt_project_paths.pop()

        # Analyze GitHub URL
        if self.analyze_type == AnalysisType.PULL_REQUEST:
            self.analyze_pull_request()
        elif self.analyze_type == AnalysisType.REPOSITORY:
            self.analyze_repository()
        else:
            raise Exception(f"Unknown analyze type: {self.analyze_type}")

    def analyze_repository(self):
        branch = self.repository.default_branch
        self.event_handler.handle_run_progress(f"Process Default Branch: '{branch}'", progress=10)
        report_path, report_url = self.generate_piperider_report(branch)
        self.result = AnalyzerResult(branch, report_path, report_url)

    def analyze_pull_request(self):
        base_branch = self.pull_request.base.ref
        base_sha = self.pull_request.base.sha
        head_branch = self.pull_request.head.ref
        head_sha = self.pull_request.head.sha if self.pull_request.merged is False \
            else self.pull_request.merge_commit_sha

        self.event_handler.handle_run_progress(f"Process Base Branch: '{base_branch}' {base_sha[0:7]}", progress=10)
        # Set environment variables for unknown branch
        with EnvContext({
            'PIPERIDER_GIT_BRANCH': base_branch,
            'PIPERIDER_GIT_SHA': base_sha,
        }):
            report_path, report_url = self.generate_piperider_report(base_sha)
            self.base_result = AnalyzerResult(base_branch, report_path, report_url)

        self.event_handler.handle_run_progress(f"Process Head Branch: '{head_branch}' {head_sha[0:7]}", progress=60)
        with EnvContext({
            'PIPERIDER_GIT_BRANCH': head_branch,
            'PIPERIDER_GIT_SHA': head_sha,
        }):
            report_path, report_url = self.generate_piperider_report(head_sha)
            self.head_result = AnalyzerResult(head_branch, report_path, report_url)

        self.event_handler.handle_run_progress(f"Compare '{base_branch}'...'{head_branch}'", progress=90)
        with EnvContext({
            'GITHUB_PR_ID': self.pull_request.number,
            'GITHUB_PR_URL': self.pull_request.html_url,
            'GITHUB_PR_TITLE': self.pull_request.title
        }):
            report_path, report_url = self.compare_piperider_reports()
            self.result = AnalyzerResult(f'{head_branch}_vs_{base_branch}', report_path, report_url)

    def ping(self):
        return "pong 🏓 🏓 🏓 \n Github URL: " + self.url

    def handle_run_start(self):
        if self.event_handler:
            self.event_handler.handle_run_start()

    def handle_run_end(self):
        if self.event_handler:
            self.event_handler.handle_run_end()

    def done(self):
        return self.dbt_project_paths == []
