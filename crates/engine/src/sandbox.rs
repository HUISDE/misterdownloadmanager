//! Folders a Flatpak sandbox would lose (#148). In the Flathub build, MDM sees only the folders
//! its permissions grant (Downloads), those chosen through the file chooser's portal, and its own
//! data; every other path in the home folder or elsewhere is in the sandbox's own memory
//! (bubblewrap's tmpfs root), which accepts files and forgets them when MDM closes. A download is
//! never saved there: it fails at once, saying why.

use std::path::Path;

/// Whether `folder` (or the folder it would be made in) is in a Flatpak sandbox's own memory:
/// on the sandbox root's file system rather than a folder the sandbox was given. Always false
/// outside a Flatpak, and on Windows and macOS.
pub fn lost_on_exit(folder: &Path) -> bool {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::MetadataExt;
        static FLATPAK: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        if !*FLATPAK.get_or_init(|| Path::new("/.flatpak-info").exists()) {
            return false;
        }
        let Ok(root) = std::fs::metadata("/") else {
            return false;
        };
        // The nearest folder that is there: the one the rest would be created in.
        let mut at = Some(folder);
        while let Some(p) = at {
            if let Ok(m) = std::fs::metadata(p) {
                return m.dev() == root.dev();
            }
            at = p.parent();
        }
        false
    }
    // Flatpak is Linux's alone.
    #[cfg(not(target_os = "linux"))]
    {
        let _ = folder;
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Outside a sandbox (the tests' machine), nothing is lost.
    #[test]
    fn outside_a_flatpak_nothing_is_lost() {
        if Path::new("/.flatpak-info").exists() {
            return;
        }
        let d = tempfile::tempdir().unwrap();
        assert!(!lost_on_exit(d.path()));
        assert!(!lost_on_exit(&d.path().join("not/made/yet")));
    }
}
