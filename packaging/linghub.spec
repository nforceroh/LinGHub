# Built from the wheel that `scripts/build-rpm.sh` produces, not from the
# source tree: the wheel is the artifact that is tested, and installing its
# .dist-info is what lets a packaged install report its app version
# (ADR-0009, ADR-0011).
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
BuildArch:      noarch
BuildRequires:  python3-rpm-macros
BuildRequires:  systemd-rpm-macros
BuildRequires:  unzip

%description
%{_description}

%package -n python3-linghub
Summary:        %{summary}
Requires:       python3-dbus-fast >= 5.2
Requires:       systemd
%{?python_provide:%python_provide python3-linghub}

%description -n python3-linghub
%{_description}

This package is the daemon and the command-line interface. It needs no
graphical toolkit, so it can be installed on a headless machine.

%package ui
Summary:        Graphical interface and tray icon for LinGHub
Requires:       python3-linghub = %{version}-%{release}
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       libappindicator-gtk3

%description ui
The GTK4 window for editing profiles and the GTK3 tray icon for switching
them. The tray is a separate process because GTK3 and GTK4 cannot be loaded
into one process.

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

%files -n python3-linghub
%license LICENSE
%{python3_sitelib}/linghub/
%{python3_sitelib}/linghub-%{version}.dist-info/
%{_bindir}/linghub
%{_userunitdir}/linghub.service
%{docdir}/config.example.json

%files ui
%{_userunitdir}/linghub-tray.service
%{_datadir}/applications/org.linghub.LinGHub.desktop
%{_metainfodir}/org.linghub.LinGHub.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/org.linghub.LinGHub.svg

%changelog
* Thu Nov 19 2026 LinGHub contributors - 0.5.0-1
- First packaged release.
