# Senza Studio desktop packaging

Production desktop artifacts are built from a clean frontend install, a hashed
Python 3.12 runtime, hashed Python wheels, the frontend production bundle, and a
real Agent Team runtime binary.

## Build

```bash
export SENZA_STUDIO_AGENT_TEAM_BIN=/path/to/agent-studio
cd studio_frontend
npm run package:desktop:linux
```

Build Windows on a native x86_64 Windows host with Git Bash:

```bash
export SENZA_STUDIO_AGENT_TEAM_BIN=/path/to/agent-studio.exe
bash scripts/package-desktop.sh win
```

The build fails if the Agent Team binary is missing, if the Python runtime
checksum does not match `packaging/python-runtime.json`, or if a locked Python
dependency cannot be installed from a hashed wheel.

The output is written to `dist/desktop`. Linux uses AppImage, Windows uses a
signed NSIS installer, and macOS uses a signed and notarized DMG. All desktop
builds must run on their target operating systems.

The Agent Team source repository and commit are pinned in
`packaging/agent-team-runtime.json`. Native Windows CI checks out that commit
and builds the runtime with `cargo build --release --workspace --all-features`.

## Windows code signing

Windows builds require a PFX certificate, its password, and `signtool.exe` from
the Windows SDK. `WIN_CSC_LINK` may be a local PFX path, an HTTPS URL, or the
base64-encoded PFX format accepted by Electron Builder. Set:

```bash
export WIN_CSC_LINK=/path/to/certificate.pfx
export WIN_CSC_KEY_PASSWORD=certificate-password
export SENZA_STUDIO_WINDOWS_CERTIFICATE_THUMBPRINT=optional-signer-thumbprint
```

`SIGNTOOL_PATH` may be set explicitly; otherwise the packaging script searches
the installed Windows SDK for an x64 `signtool.exe`. The build rejects a
missing certificate or signing tool. Electron Builder signs the application,
Agent Team runtime, Python executable, backend scripts, helper executables, and
NSIS installer. The packaging script then verifies the installer with
Authenticode and fails unless the signature is valid (and matches the optional
expected thumbprint).

Tag CI builds use the `WINDOWS_CSC_LINK`, `WINDOWS_CSC_KEY_PASSWORD`, and
`WINDOWS_CERTIFICATE_THUMBPRINT` secrets. Ordinary CI builds use a temporary
self-signed code-signing certificate that is trusted only for that test run.

## Release artifacts

Desktop installers use the stable name
`senza-studio-${version}-${os}-${arch}.${ext}`. Each installer has a sibling
`.sha256` file containing its SHA-256 digest and basename.

Verify a Windows artifact with:

```bash
(cd dist/desktop && sha256sum -c senza-studio-*-win-x64.exe.sha256)
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File scripts/verify-windows-artifact.ps1 \
  -ArtifactPath dist/desktop/senza-studio-*-win-x64.exe \
  -ExpectedThumbprint optional-signer-thumbprint
```

## Packaged E2E

On Linux, validate the artifact with:

```bash
artifact=$(find dist/desktop -maxdepth 1 -type f -name 'senza-studio-*-linux-x64.AppImage' -print -quit)
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 build/desktop-resources/python/bin/python \
  scripts/test_packaged_desktop.py "$artifact"
```

On Windows, validate the real NSIS installer with:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$artifact = (Get-ChildItem dist\desktop -Filter "senza-studio-*-win-x64.exe" |
  Select-Object -First 1).FullName
build\desktop-resources\python\python.exe `
  scripts\test_packaged_desktop.py "$artifact" `
  --timeout 180
```

The Linux test starts the real AppImage under `xvfb-run`. The Windows test
installs the real NSIS artifact silently. Both verify the public health
endpoint, confirm that the static UI and private API require authentication,
and confirm that the complete process tree exits. The Linux test also checks
that the backend receives the Studio API token and that the Agent Team process
does not receive it; Windows does not expose another process's environment to
an unprivileged test. The Windows test uses an explicit
`--user-data-dir`, verifies packaged resource checksums, confirms that Python
does not load user-site packages, kills the Agent Team runtime and waits for
its supervisor to restart it, verifies graceful shutdown diagnostics, and
force-kills the host to check child-process cleanup.

## Current platform boundary

The Linux AppImage and Windows NSIS paths are built and validated natively.
macOS packaging metadata is present, but release-quality validation still
requires native signing credentials, notarization setup, and a packaged E2E run
on macOS. Unsigned artifacts are intentionally rejected for release targets.
