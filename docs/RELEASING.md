# Releasing Uma Legacy Linker

## Automated Windows release

1. Update `APP_VERSION` in `ui_qt/core.py` and the four-part versions in `windows_version_info_qt.txt`.
2. Update `CHANGELOG.md` and any affected README/docs sections.
3. Install `requirements-build-qt.txt`, then run the portable test and translation checks:

   ```powershell
   py -m pytest -q tests --ignore=tests/test_qt_runtime.py
   py tests/check_i18n.py
   ```

4. Run `build_windows_qt.ps1 -SkipInstall -RunLayoutAudit` on Windows when a local release build is
   required. The script discovers every Qt runtime test, runs each in a fresh process, performs the
   visual audit and creates the ZIP/checksum pair. GitHub Actions executes the same command.
5. Confirm that `APP_VERSION`, Windows metadata, the newest changelog section and the release tag
   agree. `tests/test_release_consistency.py` enforces the repository-side values.
6. Commit and push the release changes.
7. Create and push the matching tag:

   ```powershell
   git tag v1.7.2
   git push origin v1.7.2
   ```

The `Windows release` workflow runs the tests and full visual layout audit on Windows, builds the packaged bundle, computes its SHA-256 checksum and attaches both files to the GitHub release. The visual QA report is uploaded even when the audit fails.

The workflow can be run manually from the Actions tab when a test build is needed without publishing a release.

## Local Windows build

From PowerShell:

```powershell
.\build_windows_qt.ps1
```

Add `-RunLayoutAudit` to reproduce the complete workflow verification locally.

Outputs:

- `dist\UmaLegacyLinkerQt-win64.zip`;
- `dist\UmaLegacyLinkerQt-win64.zip.sha256`.

The bundle is self-contained. The target PC does not need Python, PySide6, PyYAML or manually
copied default-profile JSON files. The profiles are bundled inside the extracted application
directory. Extract the whole ZIP before launching `UmaLegacyLinkerQt.exe`.

## Verification

On the download machine:

```powershell
Get-FileHash .\UmaLegacyLinkerQt-win64.zip -Algorithm SHA256
Get-Content .\UmaLegacyLinkerQt-win64.zip.sha256
```

The hashes must match.

## Windows reputation and signing

The current build is not Authenticode-signed. Windows SmartScreen may therefore warn on the first launches of a new release. Removing that warning reliably requires a trusted code-signing certificate and a signing step in the workflow; do not bypass this by distributing a private certificate or key in the repository.
