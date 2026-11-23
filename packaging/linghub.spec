# Built from the wheel that `scripts/build-rpm.sh` produces, not from the
# source tree: the wheel is the artifact that is tested, and installing its
# .dist-info is what lets a packaged install report its app version
# (ADR-0009, ADR-0011).
#
# One package. The old python3-linghub / linghub-ui split served a headless
# install that no user of this project ever had; every install is a desktop
# machine with the mouse plugged in, and CLI and GUI share one source tree
# and one version (ADR-0011 records the reversal).
%global debug_package %{nil}
%global docdir %{_datadir}/doc/%{name}
%global _description %{expand:
LinGHub edits named profiles for the Logitech G502 family — button bindings,
DPI table, LED settings and report rate — and loads the right one into the
mouse when a game starts. It talks to ratbagd over the system D-Bus and writes
every binding to the mouse's own memory, so games see real hardware events.}

Name:           linghub
Version:        @VERSION@
Release:        1%{?dist}
Summary:        Profile manager for the Logitech G502 family
License:        MIT
URL:            https://github.com/nforceroh/LinGHub
Source0:        %{name}-%{version}-py3-none-any.whl
Source1:        org.linghub.LinGHub.desktop
Source2:        org.linghub.LinGHub.metainfo.xml
Source3:        org.linghub.LinGHub.svg
Source4:        linghub.service
Source5:        linghub-tray.service
Source6:        config.example.json
Source7:        LICENSE
Source8:        linghub-retrigger
Source9:        linghub-retrigger.service
Source10:       org.linghub.Retrigger.conf
Source11:       org.linghub.retrigger-node.policy
BuildArch:      noarch
BuildRequires:  python3-rpm-macros
BuildRequires:  systemd-rpm-macros
BuildRequires:  unzip
Requires:       python3-dbus-fast >= 5.0
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       libappindicator-gtk3
Requires:       systemd

%description
%{_description}

%prep
# The wheel is the source: unpack it rather than a tarball.
rm -rf %{_builddir}/wheel
mkdir -p %{_builddir}/wheel
cd %{_builddir}/wheel
unzip -q %{SOURCE0}
# %license reads from the build directory, not the buildroot.
cp %{SOURCE7} %{_builddir}/LICENSE

%build
# Nothing to build: the wheel is already built and tested.

%install
cd %{_builddir}/wheel
# The package tree and its .dist-info, so importlib.metadata can report the
# version a packaged install is running.
mkdir -p %{buildroot}%{python3_sitelib}
cp -a linghub %{buildroot}%{python3_sitelib}/
cp -a linghub-%{version}.dist-info %{buildroot}%{python3_sitelib}/

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/linghub <<'WRAPPER'
#!/usr/bin/python3
import sys
from linghub.cli import main
sys.exit(main())
WRAPPER
chmod 0755 %{buildroot}%{_bindir}/linghub

mkdir -p %{buildroot}%{_userunitdir}
install -m 0644 %{SOURCE4} %{buildroot}%{_userunitdir}/linghub.service
install -m 0644 %{SOURCE5} %{buildroot}%{_userunitdir}/linghub-tray.service

mkdir -p %{buildroot}%{_datadir}/applications
install -m 0644 %{SOURCE1} %{buildroot}%{_datadir}/applications/
mkdir -p %{buildroot}%{_metainfodir}
install -m 0644 %{SOURCE2} %{buildroot}%{_metainfodir}/
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 %{SOURCE3} %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/

mkdir -p %{buildroot}%{docdir}
install -m 0644 %{SOURCE6} %{buildroot}%{docdir}/

# The retrigger helper: a root-owned one-method D-Bus service, activated on
# demand, gated by its own polkit action (#19). Deleted with the package.
mkdir -p %{buildroot}%{_libexecdir}
install -m 0755 %{SOURCE8} %{buildroot}%{_libexecdir}/linghub-retrigger
mkdir -p %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE9} %{buildroot}%{_unitdir}/linghub-retrigger.service
mkdir -p %{buildroot}%{_datadir}/dbus-1/system.d
install -m 0644 %{SOURCE10} %{buildroot}%{_datadir}/dbus-1/system.d/org.linghub.Retrigger.conf
mkdir -p %{buildroot}%{_datadir}/polkit-1/actions
install -m 0644 %{SOURCE11} %{buildroot}%{_datadir}/polkit-1/actions/org.linghub.retrigger-node.policy

%files
%license LICENSE
%{python3_sitelib}/linghub/
%{python3_sitelib}/linghub-%{version}.dist-info/
%{_bindir}/linghub
%{_userunitdir}/linghub.service
%{_userunitdir}/linghub-tray.service
%{_datadir}/applications/org.linghub.LinGHub.desktop
%{_metainfodir}/org.linghub.LinGHub.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/org.linghub.LinGHub.svg
%{docdir}/config.example.json
%{_libexecdir}/linghub-retrigger
%{_unitdir}/linghub-retrigger.service
%{_datadir}/dbus-1/system.d/org.linghub.Retrigger.conf
%{_datadir}/polkit-1/actions/org.linghub.retrigger-node.policy

%changelog
* Thu Nov 19 2026 LinGHub contributors - 0.5.0-1
- First packaged release.
