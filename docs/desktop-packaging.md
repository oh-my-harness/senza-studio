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

The build fails if the Agent Team binary is missing, if the Python runtime
checksum does not match `packaging/python-runtime.json`, or if a locked Python
dependency cannot be installed from a hashed wheel.

The output is written to `dist/desktop`. Linux uses AppImage. macOS uses a signed
and notarized DMG; Windows uses a signed NSIS installer. macOS and Windows
builds must run on their target operating systems and fail when code signing is
unavailable.

## Packaged E2E

On Linux, validate the artifact with:

```bash
artifact=$(find dist/desktop -maxdepth 1 -type f -name 'Senza Studio-*.AppImage' -print -quit)
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 build/desktop-resources/python/bin/python \
  scripts/test_packaged_desktop.py "$artifact"
```

The test starts the real AppImage under `xvfb-run`, verifies the public health
endpoint, confirms that the static UI requires the private API cookie, checks
that the Agent Team process does not receive the Studio API token, verifies that
the backend does receive it, and confirms the complete process tree exits.

## Current platform boundary

The Linux AppImage path is the first fully packaged path. macOS and Windows
packaging metadata is present, but release-quality validation still requires
their native signing credentials, notarization setup, and packaged E2E runs on
those platforms. Unsigned artifacts are intentionally rejected for release
targets.
