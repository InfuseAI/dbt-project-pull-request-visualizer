import os
import re

from github import Github, Auth

from core.dbt import run_dbt_deps_command, run_dbt_parse_command
from core.piperider import piperider_run_command, piperider_compare_reports_command
from core.utils import clone_github_repo, parse_github_pr_url, parse_github_url, console
from dbt_project_visualizer import patch_dbt_profiles, find_dbt_project

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')


class DbtProjectAnalyzer(object):
    def __init__(self, url: str, api_token: str = None, project_name: str = None, upload: bool = False):
        self.url = url

        auth = None
        if GITHUB_TOKEN:
            auth = Auth.Token(GITHUB_TOKEN)
        self.github = Github(auth=auth)

        # Github
        self.repo = None
        self.pull_request = None

        # Git
        self.git_repo = None
        self.base_branch = None
        self.head_branch = None
        self.project_path = None

        # Dbt
        self.dbt_project_path = None

        # Control
        self.upload = upload
        self.project_name = project_name
        self.api_token = api_token

    def load_github_url(self) -> bool:
        # Check URL format
        ret, repo_name, pr_id = parse_github_pr_url(self.url)
        if ret is False:
            ret, repo_name = parse_github_url(self.url)
            if ret is False:
                return False

        repo = self.github.get_repo(repo_name)
        if repo is None:
            return False

        self.git_repo, self.project_path = clone_github_repo(repo)
        self.base_branch = repo.default_branch
        self.repo = repo
        self.dbt_project_path = find_dbt_project(self.project_path)

        if pr_id:
            pr = repo.get_pull(pr_id)
            if pr is None:
                return False
            self.base_branch = pr.base.ref
            self.head_branch = pr.head.ref
            self.pull_request = pr
        return True

    def generate_piperider_report(self, branch) -> str:
        self.git_repo.git.checkout(branch)
        if self.dbt_project_path is None:
            raise Exception("Failed to find dbt_project.yml")

        patch_dbt_profiles(self.dbt_project_path)
        run_dbt_deps_command(self.dbt_project_path)
        run_dbt_parse_command(self.dbt_project_path)

        piperider_output_path = os.path.join('results', self.repo.full_name, branch)
        os.makedirs(piperider_output_path, exist_ok=True)
        options = {
            'output': piperider_output_path
        }

        if self.upload:
            options['api_token'] = self.api_token
            options['upload_project'] = self.project_name
        console_output = piperider_run_command(self.dbt_project_path, options=options)
        if self.upload:
            match = re.search(r'Report #.* URL: (\S+)\n', console_output)
            if match:
                return match.group(1)
        else:
            report_path = os.path.abspath(os.path.join(piperider_output_path, 'index.html'))
            console.print(f'PipeRider Report: {report_path}')

            return report_path

    def compare_piperider_reports(self):
        compare_output_path = os.path.join('results', self.repo.full_name, f'{self.head_branch}_vs_{self.base_branch}')
        os.makedirs(compare_output_path, exist_ok=True)

        # Compare the latest 2 reports
        options = {}
        if self.upload:
            options['api_token'] = self.api_token
            options['upload_project'] = self.project_name
        console_output = piperider_compare_reports_command(self.dbt_project_path, compare_output_path,
                                                           options=options)
        if self.upload:
            match = re.search(r'Comparison report URL: (\S+)\n', console_output)
            if match:
                return match.group(1)

        report_path = os.path.abspath(os.path.join(compare_output_path, 'index.html'))
        return report_path

    def summary(self, base_report=None, head_report=None, compare_report=None):
        console.rule(f"Summary")
        if base_report and head_report and compare_report:
            # PR summary
            summary = f'''
# Dbt Project {self.repo.full_name} Pull Request #{self.pull_request.number} Summary
- Repo URL: {self.repo.html_url}
- PR URL: {self.pull_request.html_url}
- PR Title: {self.pull_request.title}

## Branches - {self.pull_request.base.ref} <- {self.pull_request.head.ref}
- Compare Report: {compare_report}

### Base Branch - {self.pull_request.base.ref}
- Report: {base_report}

### Head Branch - {self.pull_request.head.ref}
- Report: {head_report}
'''
        else:
            # Repo summary
            summary = f'''
# Dbt Project {self.repo.full_name} Repository Summary
- Repo URL: {self.repo.html_url}

## Default Branch - {self.repo.default_branch}
- Report: {base_report}
'''

        from rich.markdown import Markdown
        from rich.panel import Panel
        half_width = console.width // 2
        if half_width < 140:
            half_width = 140

        panel = Panel(Markdown(summary), width=half_width, expand=False)
        console.print(panel)
        if os.getenv('GITHUB_ACTIONS') == 'true':
            with open('summary.md', 'w') as f:
                f.write(summary)

    def analyze(self):
        base_report = None
        head_report = None
        compare_report = None

        if self.load_github_url() is False:
            raise Exception(f"Failed to load github url: {self.url}")

        if self.base_branch:
            console.rule(f"Process Base Branch: '{self.base_branch}'")
            base_report = self.generate_piperider_report(self.base_branch)

        if self.head_branch:
            console.rule(f"Process Head Branch: '{self.head_branch}'")
            head_report = self.generate_piperider_report(self.head_branch)

        if self.base_branch and self.head_branch:
            console.rule(f"Compare '{self.head_branch}' vs '{self.base_branch}'")
            compare_report = self.compare_piperider_reports()

        return self.summary(base_report, head_report, compare_report)
