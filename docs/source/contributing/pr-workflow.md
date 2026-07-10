<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Pull Request Workflow

We welcome contributions. Follow the steps below.

## Pull Request Process

1. **Fork** the upstream repository and clone your fork.
2. Create a focused **branch** from `develop`, make changes, and add or update tests.
3. Run the relevant local checks and record the exact commands in the PR description.
4. **Push** to your fork and open a **Pull Request** into `develop`, unless a maintainer asks you to target a release branch.
5. Wait for maintainer vetting. copy-pr-bot mirrors trusted PRs to `pull-request/<PR number>` branches after a maintainer or configured vetter comments `/ok to test`.
6. Address review feedback until required checks, code-owner review, and review-thread resolution pass.
7. Maintainers merge with the configured bot workflow when `/merge` is available; otherwise they use the repository's normal protected-branch merge flow.

## Local Checks

Run the narrowest checks that cover your change.

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For UI changes:

```bash
cd frontends/ui
npm ci
npm run lint
npm run type-check
npm run test:ci
npm run build
```

Repository owners, organization members, and collaborators may request additional validation, including NVSkills validation with `/nvskills-ci`.

## Sign-Off and DCO

We require that all contributors **sign off** on their commits (Developer's Certificate of Origin). Commits that are not signed off will not be accepted.

To sign off on a commit:

```bash
git commit -s -m "Your message"
```

This appends a line such as:

```
Signed-off-by: Your Name <your@email.com>
```

## Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
(b) The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
(c) The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
(d) I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.
