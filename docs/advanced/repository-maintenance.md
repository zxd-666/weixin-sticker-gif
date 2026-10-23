# Repository maintenance

## Public media

Keep compact, reviewable style examples in `gallery/styles/` and the three GIF previews used by the README. Do not commit complete sticker workspaces, raw videos, private reference images, finished album ZIPs, or credentials. The tracked media budget is 12 MiB.

`scripts/check_repository_policy.py` checks the README sections and previews, rejects tracked files under `examples/`, `promo-v020/`, and `works/`, enforces the media budget, and requires the release workflow. The Python and Node suites, style checks, and benchmarks run in CI.

## Licensing and provenance

New contributions use [PolyForm Noncommercial 1.0.0](../../LICENSE). Previously MIT-licensed portions retain their original license and copyright notice in [LICENSE.upstream](../../LICENSE.upstream). Do not remove provenance records from gallery examples or imply that third-party reference images and model outputs are covered by the code license.

## Releases

Use `.github/workflows/release.yml` for tagged releases. It verifies `main` before publishing and needs a source ref with the full gallery media when a gallery archive is attached. Check the version in `package.json`, the top heading in `RELEASE_NOTES.md`, and `gallery/release-manifest.json` before running it. Direct tags and manually assembled release archives bypass these checks.
