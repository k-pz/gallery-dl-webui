# Contributing

## Branching — trimmed gitflow

This repo uses a two-branch flow:

- **`main`** — released code only. Tagged `vX.Y.Z` for every release. The
  LXC deploy script (`scripts/lxc-update.sh`) tracks `main`, so anything
  landing here ships to production.
- **`develop`** — integration branch. All feature work merges here first.

Day-to-day work goes on short-lived branches off `develop`:

```
develop ──▶ feature/<topic>   (new functionality)
develop ──▶ fix/<topic>       (bug fixes)
develop ──▶ chore/<topic>     (deps, tooling, docs-only)
```

Push the branch, open a PR into `develop`, get CI green, merge. Repeat
until `develop` is in a shippable state.

## Cutting a release

Open a PR from `develop` into `main` and merge it. That's the release
gesture — the [`release`](.github/workflows/release.yml) workflow fires on
the PR-close event and:

1. Reads conventional commits on `develop` since the last `v*` tag.
2. Computes the next semver and runs `cz bump` (rewrites the version
   literals listed in `.cz.toml`, appends a `CHANGELOG.md` section, makes
   a `bump: …` commit, and tags it `v$version`).
3. Pushes the bump commit + tag back to `main`.
4. Creates a GitHub Release with the new CHANGELOG section as the body.

No other path triggers a release. A direct push to `main` (rare; only
sensible for an emergency hotfix the human applies manually) does **not**
auto-bump — use the workflow's `workflow_dispatch` trigger if you want a
manual bump in that case.

## Commit messages

Commitizen reads the [conventional-commits](https://www.conventionalcommits.org/)
log to decide the next version, so messages must follow the format:

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

The bump rule:

| Commit type                                  | Effect on version |
| -------------------------------------------- | ----------------- |
| `fix:`                                       | patch (`x.y.Z`)   |
| `feat:`                                      | minor (`x.Y.0`)   |
| any type with `BREAKING CHANGE:` in the body | major (`X.0.0`)   |
| `chore:`, `docs:`, `refactor:`, `test:`, `ci:`, `perf:`, `style:` | no bump (will release if other bump-worthy commits are present) |

Recent commits in the repo are good models — check `git log` before
writing a new one.

## Hotfixes

For an emergency fix to a production-shipped release:

1. Branch `fix/<topic>` off **`main`** (not `develop`).
2. Make the fix, push, open a PR into `main`.
3. After merging the hotfix PR, manually trigger the release workflow
   (`Actions → release → Run workflow`) so the bump tag is created.
4. Open a follow-up PR merging `main` back into `develop` so the fix
   isn't lost on the next release.

## Local checks before opening a PR

```sh
mise run check       # lint + typecheck + test
mise run docs:check  # strict mkdocs build
```

CI runs the same commands; running them locally first avoids a round trip.

## Previewing the next release

Before opening a `develop → main` PR, run:

```sh
mise run release:preview
```

That invokes `cz bump --dry-run` against the current commit history and
prints the version commitizen would compute (e.g. `1.0.0 → 1.1.0`) plus
the CHANGELOG entries it would generate, without touching any files or
tags. Useful for sanity-checking that the conventional-commit log on
`develop` resolves to the version you expected.
