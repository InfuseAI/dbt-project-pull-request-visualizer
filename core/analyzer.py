import os
import re
import tempfile
from enum import Enum

from github import Github, Auth, Repository, PullRequest

from core.dbt import dbt_deps, dbt_parse, find_dbt_project, patch_dbt_profiles
from core.piperider import piperider_run, piperider_compare_reports
from core.utils import clone_github_repo, parse_github_pr_url, parse_github_url, console

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')


class AnalyzerResult(object):
    def __init__(self, name: str, path: str, url: str = None):
        self.name = name
        self.path = path
        self.url = url

    @property
    def report(self):
        path = self.path if os.path.isabs(self.path) else os.path.abspath(self.path)
        return self.url or path


def _output_result_path(*args):
    if os.access(os.path.curdir, os.W_OK):
        return os.path.join('results', *args)

    tempdir = tempfile.mkdtemp()
    return os.path.join(tempdir, *args)


class AnalysisType(Enum):
    UNKNOWN = ''
    REPOSITORY = 'repository'
    PULL_REQUEST = 'pull-request'


class DbtProjectAnalyzer(object):
    def __init__(self, url: str,
                 api_token: str = None,
                 project_name: str = None,
                 upload: bool = False,
                 share: bool = False):
        self.url = url

        auth = None
        if GITHUB_TOKEN:
            auth = Auth.Token(GITHUB_TOKEN)
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
        self.dbt_project_path = None

        # Control
        self.upload = upload
        self.share = share
        self.project_name = project_name
        self.api_token = api_token

        # Analyze Results
        self.result: AnalyzerResult | None = None
        self.base_result: AnalyzerResult | None = None  # Used for PR
        self.head_result: AnalyzerResult | None = None  # Used for PR

    def verify_github_url(self, url) -> (AnalysisType, Repository, PullRequest):
        ret, repo_name, pr_id = parse_github_pr_url(url)
        if ret is False:
            ret, repo_name = parse_github_url(url)
            if ret is False:
                # Invalid GitHub URL
                raise Exception(f"Invalid GitHub URL: {url}")
            else:
                analysis_type = AnalysisType.REPOSITORY
        else:
            analysis_type = AnalysisType.PULL_REQUEST

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
        self.git_repo, self.project_path = clone_github_repo(self.repository)
        self.dbt_project_path = find_dbt_project(self.project_path)

        if self.analyze_type == AnalysisType.PULL_REQUEST:
            self.base_branch = self.pull_request.base.ref
            self.base_sha = self.pull_request.base.sha
            self.head_branch = self.pull_request.head.ref
            self.head_sha = self.pull_request.head.sha
        else:
            self.base_branch = self.repository.default_branch

        return True

    def generate_piperider_report(self, branch_or_commit) -> (str, str):
        self.git_repo.git.checkout(branch_or_commit)
        if self.dbt_project_path is None:
            raise Exception("Failed to find dbt_project.yml")

        patch_dbt_profiles(self.dbt_project_path)
        dbt_deps(self.dbt_project_path)
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
        console_output = piperider_run(self.dbt_project_path, options=options)

        report_url = None
        if self.upload:
            match = re.search(r'Report #.* URL: (\S+)\n', console_output)
            if match:
                report_url = match.group(1)

        report_path = os.path.join(piperider_output_path, 'index.html')
        console.print(f'PipeRider Report: {report_path}')

        return report_path, report_url

    def compare_piperider_reports(self) -> (str, str):
        compare_output_path = _output_result_path(self.repository.full_name,
                                                  f'{self.head_branch}_vs_{self.base_branch}')
        os.makedirs(compare_output_path, exist_ok=True)

        # Compare the latest 2 reports
        options = {}

        # Pre-compare
        if self.upload:
            options['api_token'] = self.api_token
            options['upload_project'] = self.project_name

        console_output = piperider_compare_reports(self.dbt_project_path, os.path.abspath(compare_output_path),
                                                   options=options)
        # Post-compare
        report_url = None
        if self.upload:
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

## Pull Request - {self.pull_request.base.ref} <- {self.pull_request.head.ref} #{self.pull_request.number}
- Compare Report: {self.result.report}

### Base Branch - {self.pull_request.base.ref} {self.pull_request.base.sha[0:7]}
- Report: {base_report}

### Head Branch - {self.pull_request.head.ref} {self.pull_request.head.sha[0:7]}
- Report: {head_report}
'''
        return content, panel_width

    def exec(self):
        if self.load_github_url() is False:
            raise Exception(f"Failed to load github url: {self.url}")

        if self.analyze_type == AnalysisType.PULL_REQUEST:
            return self.analyze_pull_request()
        elif self.analyze_type == AnalysisType.REPOSITORY:
            return self.analyze_repository()
        else:
            raise Exception(f"Unknown analyze type: {self.analyze_type}")

    def analyze_repository(self):
        branch = self.repository.default_branch
        console.rule(f"Process Default Branch: '{branch}'")
        report_path, report_url = self.generate_piperider_report(branch)
        self.result = AnalyzerResult(branch, report_path, report_url)

    def analyze_pull_request(self):
        base_branch = self.pull_request.base.ref
        base_sha = self.pull_request.base.sha
        head_branch = self.pull_request.head.ref
        head_sha = self.pull_request.head.sha

        console.rule(f"Process Base Branch: '{base_branch}' {base_sha[0:7]}")
        # Set environment variables for unknown branch
        os.environ['PIPERIDER_GIT_BRANCH'] = base_branch
        os.environ['PIPERIDER_GIT_SHA'] = base_sha
        report_path, report_url = self.generate_piperider_report(base_sha)
        self.base_result = AnalyzerResult(base_branch, report_path, report_url)
        # Cleanup environment variables
        del os.environ['PIPERIDER_GIT_BRANCH']
        del os.environ['PIPERIDER_GIT_SHA']

        console.rule(f"Process Head Branch: '{head_branch}' {head_sha[0:7]}")
        report_path, report_url = self.generate_piperider_report(head_branch)
        self.head_result = AnalyzerResult(head_branch, report_path, report_url)

        console.rule(f"Compare '{base_branch}'...'{head_branch}'")
        report_path, report_url = self.compare_piperider_reports()
        self.result = AnalyzerResult(f'{head_branch}_vs_{base_branch}', report_path, report_url)

    def ping(self):
        return "pong 🏓 🏓 🏓 \n Github URL: " + self.url
