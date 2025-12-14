# ml_alt_text
Template repository for ML projects

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)



The repo is setup with placeholder name `alt_text` in various files and also a placeholder for package name. To replace `alt_text` with package name of your choice, run .setup.sh executable.

```
./.setup.sh custom_package_name
```

This will update the following files as shown in logs:

```bash
Replaced in: ./pyproject.toml
Replaced in: ./README.md
Replaced in: ./environment.yaml
Renamed directory from ./alt_text to ./custom_package_name
Pre-commit hooks installed.
```

The chosen package name will serve as name allowing to do:
- `pip install <custom_package_name>`
- `conda env create -f environment.yaml`

Furthermore, pre-commit hooks will be installed.

Checklist of additional items upon using this template for Python projects

- [ ] Update CODEOWNERS
- [ ] Update PR template in `.github/pull_request_template.md`
- [ ] Ensure repository has `main` and `dev` branch
- [ ] Update `cortex-template.yaml` and (git) move it to `cortex.yaml`.. It is taken from - [`sample_cortex.yaml`](https://github.com/collectorsgroup/cortex/blob/0f5e506c302d17cb361efb88fc6cf8e40e88966d/sample-cortex.yaml), a sample file available in [`CollectorsGroup`](https://github.com/collectorsgroup/cortex/tree/0f5e506c302d17cb361efb88fc6cf8e40e88966d) repository.

The following instructions are to be followed on Github project settings:

- [ ] Use the repository name according to the [Github Repositories Naming Standard](https://id.atlassian.com/login?application=confluence&continue=https%3A%2F%2Fcollectors.atlassian.net%2Fwiki%2Fspaces%2FCloudops%2Fpages%2F507576327%2FGithub%2BRepositories%2BNaming%2BStandard).
- [ ] Add branch protection rules in the repository settings.
- [ ] Update the repository settings to allow only pull requests to the `main` and `dev` branches.
- [ ] Update the repository settings to only enable "Squash and Merge".
- [ ] Update the repository settings to allow merge with at least 2 reviewers.
- [ ] Update the repository to auto-delete feature branches upon pull request merge.
- [ ] Update "Autolink references" in the repository settings to allow automatic hyperlinking of ticket numbers.
- [ ] Add team members to the repository and provide write/maintain access to developers. Provide managers with Admin access.

This README and `setup.sh` exist to be deleted after all the above instructions are completed.
