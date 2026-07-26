# Releasing Uma Legacy Linker

## Automated Windows release

1. Update `APP_VERSION` in `ui_qt/core.py` and the four-part versions in `windows_version_info_qt.txt`.
2. Update `CHANGELOG.md`.
3. Run `python -m pytest`.
4. Commit and push the release changes.
5. Create and push the matching tag:

   ```powershell
   git tag v1.7.0
   git push origin v1.7.0
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

The bundle is self-contained. The target PC does not need Python, PySide6, PyYAML or adjacent default-profile JSON files. Extract the whole directory before launching `UmaLegacyLinkerQt.exe`.

## Verification

On the download machine:

```powershell
Get-FileHash .\UmaLegacyLinkerQt-win64.zip -Algorithm SHA256
Get-Content .\UmaLegacyLinkerQt-win64.zip.sha256
```

The hashes must match.

## Windows reputation and signing

The current build is not Authenticode-signed. Windows SmartScreen may therefore warn on the first launches of a new release. Removing that warning reliably requires a trusted code-signing certificate and a signing step in the workflow; do not bypass this by distributing a private certificate or key in the repository.
