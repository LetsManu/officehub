//! File names that work on Windows, unique within a folder, and the names of conflict copies.

/// A name Windows accepts: no `<>:"/\|?*` or control characters, no trailing dots or spaces, no reserved device
/// names (CON, PRN, AUX, NUL, COM1–9, LPT1–9).
pub fn windows_safe(name: &str) -> String {
    let mut clean: String = name
        .chars()
        .map(|c| if c < ' ' || "<>:\"/\\|?*".contains(c) { '_' } else { c })
        .collect();
    while clean.ends_with('.') || clean.ends_with(' ') {
        clean.pop();
    }
    if clean.is_empty() {
        clean.push('_');
    }
    let stem = clean.split('.').next().unwrap_or("").to_ascii_uppercase();
    let reserved = matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || ((stem.starts_with("COM") || stem.starts_with("LPT"))
            && stem.len() == 4
            && stem.as_bytes().get(3).is_some_and(|d| (b'1'..=b'9').contains(d)));
    if reserved {
        clean.insert(0, '_');
    }
    clean
}

/// Splits "Plan.docx" into ("Plan", ".docx"); names without an extension keep an empty one.
fn split(name: &str) -> (&str, &str) {
    match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i..]),
        _ => (name, ""),
    }
}

/// `name` or, if taken, "name (2)", "name (3)" … (before the extension). `taken` compares like Windows: ignoring case.
pub fn unique(name: &str, taken: impl Fn(&str) -> bool) -> String {
    if !taken(name) {
        return name.to_string();
    }
    let (stem, ext) = split(name);
    (2..10_000)
        .map(|n| format!("{stem} ({n}){ext}"))
        .find(|candidate| !taken(candidate))
        .unwrap_or_else(|| format!("{stem} ({}){ext}", uuid_like()))
}

/// The name for my version of a file someone else changed at the same time, like OneDrive:
/// "Plan (Konflikt PC-ANNA 2026-10-22).docx".
pub fn conflict_copy(name: &str, word: &str, device: &str, date: &str) -> String {
    let (stem, ext) = split(name);
    windows_safe(&format!("{stem} ({word} {device} {date}){ext}"))
}

/// Helper files programs create next to the real ones (Office lock files, temporary saves, Explorer metadata).
pub fn ignored(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    lower.starts_with("~$")
        || lower.starts_with(".~lock.")
        || lower.starts_with("._")
        || lower.ends_with(".tmp")
        || lower.ends_with(".partial")
        || lower.ends_with(".officehub-partial")
        || lower == "desktop.ini"
        || lower == "thumbs.db"
        || lower == ".ds_store"
        || (lower.starts_with('~') && lower.ends_with(".tmp"))
}

fn uuid_like() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn makes_names_windows_safe() {
        assert_eq!(windows_safe("Plan: Q1/Q2?.docx"), "Plan_ Q1_Q2_.docx");
        assert_eq!(windows_safe("Notizen. "), "Notizen");
        assert_eq!(windows_safe("CON.txt"), "_CON.txt");
        assert_eq!(windows_safe("com1"), "_com1");
        assert_eq!(windows_safe("Computer.txt"), "Computer.txt");
        assert_eq!(windows_safe(""), "_");
    }

    #[test]
    fn unique_names_count_up_before_the_extension() {
        let taken = ["plan.docx", "plan (2).docx"];
        let is_taken = |n: &str| taken.iter().any(|t| t.eq_ignore_ascii_case(n));
        assert_eq!(unique("Plan.docx", is_taken), "Plan (3).docx");
        assert_eq!(unique("Bericht.docx", is_taken), "Bericht.docx");
        assert_eq!(unique("plan", |n| n == "plan"), "plan (2)");
    }

    #[test]
    fn conflict_copies_keep_the_extension() {
        assert_eq!(
            conflict_copy("Plan.docx", "Konflikt", "PC-ANNA", "2026-10-22"),
            "Plan (Konflikt PC-ANNA 2026-10-22).docx"
        );
    }

    #[test]
    fn helper_files_are_ignored() {
        assert!(ignored("~$Plan.docx"));
        assert!(ignored("desktop.ini"));
        assert!(ignored("ABC123.tmp"));
        assert!(!ignored("Plan.docx"));
    }
}
