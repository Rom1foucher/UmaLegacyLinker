# Releasing Uma Legacy Linker

## Automated Windows release

1. Update `APP_VERSION` in `app.py` and the four-part versions in `windows_version_info.txt`.
2. Update `CHANGELOG.md`.
3. Run `python -m unittest discover -v`.
4. Commit and push the release changes.
5. Create and push the matching tag:

   ```powershell
   git tag v1.5.0
   git push origin v1.5.0
   ```

The `Windows release` workflow runs the tests on Windows, builds the standalone executable, computes its SHA-256 checksum and attaches both files to the GitHub release.

The workflow can be run manually from the Actions tab when a test build is needed without publishing a release.

## Local Windows build

From PowerShell:

```powershell
.\build_windows.ps1
```

Outputs:

- `dist\UmaLegacyLinker.exe`;
- `dist\UmaLegacyLinker.exe.sha256`.

The executable is self-contained. The target PC does not need Python, PyYAML or adjacent default-profile JSON files.

## Verification

On the download machine:

```powershell
Get-FileHash .\UmaLegacyLinker.exe -Algorithm SHA256
Get-Content .\UmaLegacyLinker.exe.sha256
```

The hashes must match.

## Windows reputation and signing

The current build is not Authenticode-signed. Windows SmartScreen may therefore warn on the first launches of a new release. Removing that warning reliably requires a trusted code-signing certificate and a signing step in the workflow; do not bypass this by distributing a private certificate or key in the repository.
