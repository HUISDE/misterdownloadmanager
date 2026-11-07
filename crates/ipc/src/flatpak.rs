//! Running as a Flatpak (the Flathub build, `packaging/flatpak/`): what its sandbox changes for
//! the app and the browser host (#148).
//!
//! Inside the sandbox the browsers installed on the system can't start a program of the
//! sandbox's own: the host manifest MDM writes for them names a small script in the app's own
//! data folder (`~/.var/app/<id>/data/…`, the same path inside and out), which runs the host with
//! `flatpak run --command=misterdownloadmanager-nmhost <id>`. The sandbox may write only the
//! browsers' host folders its manifest lists ([`NATIVE_HOST_DIRS`], kept equal to the manifest's
//! `--filesystem` lines by a test), and only those that already exist: Flatpak mounts nothing
//! that isn't there (the manifest doesn't create them in every home, browser or not).

use std::path::{Path, PathBuf};

use crate::browsers::Family;

/// The app's Flatpak ID (`com.misterdownloadmanager.MisterDownloadManager`) when this program
/// runs in a Flatpak sandbox: `/.flatpak-info`, which Flatpak puts in every sandbox, names it
/// (`FLATPAK_ID` says the same, when set). None outside one, and on Windows and macOS.
pub fn app_id() -> Option<&'static str> {
    #[cfg(target_os = "linux")]
    {
        static ID: std::sync::OnceLock<Option<String>> = std::sync::OnceLock::new();
        ID.get_or_init(|| {
            let info = std::fs::read_to_string("/.flatpak-info").ok()?;
            std::env::var("FLATPAK_ID")
                .ok()
                .filter(|id| !id.is_empty())
                .or_else(|| info_app_id(&info))
        })
        .as_deref()
    }
    // Flatpak is Linux's alone.
    #[cfg(not(target_os = "linux"))]
    None
}

/// The `name` of `/.flatpak-info`'s `[Application]` group (a keyfile).
pub fn info_app_id(info: &str) -> Option<String> {
    let mut group = "";
    for line in info.lines().map(str::trim) {
        if let Some(g) = line.strip_prefix('[').and_then(|l| l.strip_suffix(']')) {
            group = g;
        } else if group == "Application"
            && let Some(v) = line.strip_prefix("name=")
        {
            let v = v.trim();
            return (!v.is_empty()).then(|| v.to_owned());
        }
    }
    None
}

/// Where a browser host folder the manifest grants lives.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Base {
    /// The system's `$XDG_CONFIG_HOME` (`~/.config`): the manifest's `xdg-config/…`.
    XdgConfig,
    /// The home folder: the manifest's `~/…`.
    Home,
}

/// The browsers' host folders the Flatpak may write (its `--filesystem` lines), each with the
/// family whose manifest goes there: Chrome, Chromium, Edge, Brave, Vivaldi and Opera read
/// their own; Firefox and its forks (Zen, LibreWolf, Floorp, Waterfox) all read Mozilla's.
pub const NATIVE_HOST_DIRS: &[(Base, &str, Family)] = &[
    (
        Base::XdgConfig,
        "google-chrome/NativeMessagingHosts",
        Family::Chromium,
    ),
    (
        Base::XdgConfig,
        "chromium/NativeMessagingHosts",
        Family::Chromium,
    ),
    (
        Base::XdgConfig,
        "microsoft-edge/NativeMessagingHosts",
        Family::Chromium,
    ),
    (
        Base::XdgConfig,
        "BraveSoftware/Brave-Browser/NativeMessagingHosts",
        Family::Chromium,
    ),
    (
        Base::XdgConfig,
        "vivaldi/NativeMessagingHosts",
        Family::Chromium,
    ),
    (
        Base::XdgConfig,
        "opera/NativeMessagingHosts",
        Family::Chromium,
    ),
    (Base::Home, ".mozilla/native-messaging-hosts", Family::Gecko),
];

/// The manifest's `--filesystem` value for a [`NATIVE_HOST_DIRS`] entry.
pub fn permission(base: Base, dir: &str) -> String {
    match base {
        Base::XdgConfig => format!("xdg-config/{dir}"),
        Base::Home => format!("~/{dir}"),
    }
}

/// The system's own config folder, as the sandbox sees it: Flatpak points `XDG_CONFIG_HOME` at
/// the app's (`~/.var/app/<id>/config`) and gives the system's as `HOST_XDG_CONFIG_HOME`
/// (Flatpak 1.16 and later); else `~/.config`.
pub fn host_config_dir(home: &Path) -> PathBuf {
    std::env::var_os("HOST_XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| home.join(".config"))
}

/// The granted host folders that are there (mounted into the sandbox: their browser has one),
/// under `home` and `config` (the system's config folder, [`host_config_dir`]).
pub fn native_host_dirs(home: &Path, config: &Path) -> Vec<(PathBuf, Family)> {
    NATIVE_HOST_DIRS
        .iter()
        .map(|(base, dir, family)| {
            let root = match base {
                Base::XdgConfig => config,
                Base::Home => home,
            };
            (root.join(dir), *family)
        })
        .filter(|(d, _)| d.is_dir())
        .collect()
}

/// The script browsers start in the Flatpak's place, in the data folder (`data`): outside the
/// sandbox it is at the same path.
pub fn host_script_path(data: &Path) -> PathBuf {
    data.join("browser-host")
        .join("misterdownloadmanager-nmhost")
}

/// The script's text: the Flatpak's host, run by Flatpak with the browser's arguments and
/// standard streams.
pub fn host_script(app_id: &str) -> String {
    format!(
        "#!/bin/sh\n\
         # Mister Download Manager's Flatpak wrote this: browsers installed on the system start\n\
         # its helper through Flatpak. Written again at each start of the app.\n\
         exec flatpak run --command=misterdownloadmanager-nmhost {app_id} \"$@\"\n"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The manifest's sandbox permissions: a browser folder the app writes is one the manifest
    /// grants, and the manifest grants none the app doesn't write.
    #[test]
    fn host_folders_match_the_manifest() {
        let manifest = include_str!(
            "../../../packaging/flatpak/com.misterdownloadmanager.MisterDownloadManager.yml"
        );
        let granted: Vec<&str> = manifest
            .lines()
            .filter_map(|l| l.trim().strip_prefix("- --filesystem="))
            .map(|v| v.split_whitespace().next().unwrap_or(v))
            .filter(|v| v.contains("NativeMessagingHosts") || v.contains("native-messaging-hosts"))
            .collect();
        let ours: Vec<String> = NATIVE_HOST_DIRS
            .iter()
            .map(|(b, d, _)| permission(*b, d))
            .collect();
        assert_eq!(granted, ours);
        assert!(manifest.contains("id: com.misterdownloadmanager.MisterDownloadManager"));
    }

    /// Flathub and the software centres list the releases from the metainfo: each release in
    /// CHANGELOG.md, with its date, newest first, and no other.
    #[test]
    fn metainfo_lists_the_changelogs_releases() {
        let changelog = include_str!("../../../CHANGELOG.md");
        let metainfo = include_str!(
            "../../../packaging/flatpak/com.misterdownloadmanager.MisterDownloadManager.metainfo.xml"
        );
        let released: Vec<(String, String)> = changelog
            .lines()
            .filter_map(|l| l.strip_prefix("## ["))
            .filter_map(|l| {
                let (version, rest) = l.split_once("] - ")?;
                Some((version.to_owned(), rest.trim().to_owned()))
            })
            .collect();
        let listed: Vec<(String, String)> = metainfo
            .lines()
            .filter_map(|l| l.trim().strip_prefix("<release version=\""))
            .filter_map(|l| {
                let (version, rest) = l.split_once('"')?;
                let date = rest.split_once("date=\"")?.1.split_once('"')?.0;
                Some((version.to_owned(), date.to_owned()))
            })
            .collect();
        assert!(!released.is_empty());
        assert_eq!(
            listed, released,
            "packaging/flatpak's metainfo: add a <release> for each CHANGELOG release"
        );
    }

    #[test]
    fn app_id_from_flatpak_info() {
        let info = "[Application]\nname=com.misterdownloadmanager.MisterDownloadManager\n\
                    runtime=runtime/org.freedesktop.Platform/x86_64/26.08\n\n\
                    [Instance]\nname=other\n";
        assert_eq!(
            info_app_id(info).as_deref(),
            Some("com.misterdownloadmanager.MisterDownloadManager")
        );
        assert_eq!(info_app_id("[Instance]\nname=x\n"), None);
        assert_eq!(info_app_id(""), None);
    }

    #[test]
    fn only_folders_that_are_there() {
        let h = tempfile::tempdir().unwrap();
        let home = h.path();
        let config = home.join(".config");
        assert!(native_host_dirs(home, &config).is_empty());
        std::fs::create_dir_all(config.join("google-chrome/NativeMessagingHosts")).unwrap();
        std::fs::create_dir_all(home.join(".mozilla/native-messaging-hosts")).unwrap();
        // A browser's folder without its host folder: not mounted, nothing to write.
        std::fs::create_dir_all(config.join("chromium")).unwrap();
        assert_eq!(
            native_host_dirs(home, &config),
            vec![
                (
                    config.join("google-chrome/NativeMessagingHosts"),
                    Family::Chromium
                ),
                (home.join(".mozilla/native-messaging-hosts"), Family::Gecko),
            ]
        );
    }

    #[test]
    fn script_runs_the_flatpaks_host() {
        let s = host_script("com.misterdownloadmanager.MisterDownloadManager");
        assert!(s.starts_with("#!/bin/sh\n"));
        assert!(s.contains(
            "exec flatpak run --command=misterdownloadmanager-nmhost \
             com.misterdownloadmanager.MisterDownloadManager \"$@\""
        ));
    }
}
