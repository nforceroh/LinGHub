#!/usr/bin/env bash
# Build the LinGHub RPM from a wheel.
#
# The wheel is the artifact: it is what the tests run against and what a
# non-Fedora user can install. The RPM wraps it, so the two cannot disagree
# about what is inside.
#
# Usage: scripts/build-rpm.sh [--no-smoke-test]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_DIR/dist"
TOP_DIR="$DIST_DIR/rpmbuild"
PYTHON="${LINGHUB_PYTHON:-$REPO_DIR/.venv/bin/python}"
SMOKE_TEST=yes

for arg in "$@"; do
    case "$arg" in
        --no-smoke-test) SMOKE_TEST=no ;;
        *) echo "Error: unknown argument $arg" >&2; exit 2 ;;
    esac
done

if ! command -v rpmbuild >/dev/null; then
    echo "Error: rpmbuild not found. Install it with: sudo dnf install rpm-build" >&2
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "Error: no interpreter at $PYTHON" >&2
    exit 1
fi

# A packaged release must not carry a dev version: the RPM version field
# would change with every commit and the tag would mean nothing.
VERSION="$("$PYTHON" -c 'from linghub import version; print(version.current())')"
case "$VERSION" in
    *+*|*dirty*|unknown)
        echo "Error: refusing to package version '$VERSION'." >&2
        echo "Tag a release and build from a clean tree (see ADR-0009)." >&2
        exit 1
        ;;
esac

echo "Building linghub $VERSION"

rm -rf "$TOP_DIR"
mkdir -p "$TOP_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

echo "Building the wheel"
"$PYTHON" -m pip wheel "$REPO_DIR" --no-deps -w "$TOP_DIR/SOURCES" -q

WHEEL="$TOP_DIR/SOURCES/linghub-$VERSION-py3-none-any.whl"
if [ ! -f "$WHEEL" ]; then
    echo "Error: expected $WHEEL, found:" >&2
    ls "$TOP_DIR/SOURCES" >&2
    exit 1
fi

echo "Staging the spec's sources"
cp "$REPO_DIR/packaging/org.linghub.LinGHub.desktop" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/org.linghub.LinGHub.metainfo.xml" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/icons/org.linghub.LinGHub.svg" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/units/linghub.service" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/units/linghub-tray.service" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/config.example.json" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/LICENSE" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/system/linghub-retrigger" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/system/linghub-retrigger.service" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/system/org.linghub.Retrigger.conf" "$TOP_DIR/SOURCES/"
cp "$REPO_DIR/packaging/system/org.linghub.retrigger-node.policy" "$TOP_DIR/SOURCES/"

sed "s|@VERSION@|$VERSION|" "$REPO_DIR/packaging/linghub.spec" > "$TOP_DIR/SPECS/linghub.spec"

echo "Running rpmbuild"
rpmbuild --define "_topdir $TOP_DIR" -bb "$TOP_DIR/SPECS/linghub.spec"

BUILT="$(find "$TOP_DIR/RPMS" -name "linghub-$VERSION-*.noarch.rpm")"
if [ -z "$BUILT" ]; then
    echo "Error: rpmbuild produced no RPMs" >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
rm -f "$DIST_DIR"/*.rpm
cp "$TOP_DIR"/RPMS/noarch/*.rpm "$DIST_DIR/"
echo "Built:"
ls -1 "$DIST_DIR"/*.rpm

if [ "$SMOKE_TEST" = "no" ]; then
    exit 0
fi

# Unpack the package into a throwaway directory and import it from there.
# This catches a %files list that does not match what the wheel contains,
# which is the failure a build alone cannot see. rpm2cpio needs no root.
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

echo "Smoke-testing in $ROOT"
BASE_RPM="$(find "$DIST_DIR" -name "linghub-$VERSION-*.noarch.rpm" -print -quit)"
if [ -z "$BASE_RPM" ]; then
    echo "Error: no linghub RPM in $DIST_DIR" >&2
    exit 1
fi
# rpm2cpio exits 141 (SIGPIPE) once cpio has what it needs, which pipefail
# would turn into a failure. Going through a file avoids the pipeline.
rpm2cpio "$BASE_RPM" > "$ROOT/payload.cpio" || true
(cd "$ROOT" && cpio -idm --quiet < payload.cpio)
rm -f "$ROOT/payload.cpio"

SITELIB="$(find "$ROOT/usr/lib" -maxdepth 3 -name "linghub" -type d -print -quit)"
if [ -z "$SITELIB" ]; then
    echo "Error: the package installed no linghub module" >&2
    exit 1
fi

if [ ! -x "$ROOT/usr/bin/linghub" ]; then
    echo "Error: /usr/bin/linghub is missing from the package" >&2
    exit 1
fi

PYTHONPATH="$(dirname "$SITELIB")" "$PYTHON" -c "
import linghub, linghub.ui.buttonmap as b
from importlib.metadata import version
print('module:', linghub.__file__)
print('version:', version('linghub'))
assert b.DIAGRAM_IMAGE.exists(), b.DIAGRAM_IMAGE
assert b.PACKAGED_HOTSPOTS.exists(), b.PACKAGED_HOTSPOTS
print('assets: ok')
"

echo "Smoke test passed"
