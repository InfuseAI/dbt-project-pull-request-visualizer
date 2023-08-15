# DBT Project Pull-Request Visualizer
A tool to visualize the GitHub Pull Request of a dbt project

## How it works

### Input
- GitHub Pull Request URL
  - PR ID
  - GitHub Repository Name

### Output
- A shareable PipeRider report URL

### Work Flow
- Clone the repository 
- Checkout to the target branch
- Install the Python packages if we can find `requirements.txt` in the repository
- Generate a fake `profiles.yml` file if we can't find one in the repository
- Run `dbt deps` to install the dependencies
- Run `dbt parse` to parse the project and generate the manifest file
- Checkout to the base branch
- Run `dbt parse` to parse the project and generate the manifest file
- Compare the two manifest files by PipeRider and generate a share report

