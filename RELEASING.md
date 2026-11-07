# Releasing

Publishing runs on GitHub Actions with PyPI **trusted publishing**, so no API tokens are
stored anywhere.

## One-time setup

1. Push this repo to GitHub (the URLs in `pyproject.toml` point at `honnuanand/showrun`;
   change them if you use a different repo).
2. On PyPI, go to **Your account → Publishing → Add a new pending publisher**:
   - PyPI project name: `showrun-cli`
   - Owner: `honnuanand`, Repository: `showrun`
   - Workflow name: `publish.yml`, Environment: `pypi`
3. Do the same on https://test.pypi.org with environment `testpypi` (optional, but
   useful for a dry run).
4. In the GitHub repo, open **Settings → Environments** and create `pypi` and `testpypi`.
   Adding yourself as a required reviewer on `pypi` gives you a manual approve step.

## Each release

1. Bump `__version__` in `src/showrun/__init__.py`.
2. Commit, then tag and push:
   ```bash
   git commit -am "Release 0.1.1"
   git tag v0.1.1
   git push origin main v0.1.1
   ```
3. The **Publish** workflow checks that the tag matches `__version__`, runs the tests,
   builds, publishes to PyPI and creates a GitHub release with the wheel and sdist.

To test without a release, open **Actions → Publish → Run workflow** to publish the
current main to TestPyPI, then:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple showrun-cli
```
