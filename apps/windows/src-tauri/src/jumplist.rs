//! Like Teams: a right click on OfficeHub in the taskbar offers the everyday places (chat, calendar, meetings,
//! activity). Each entry starts the app with `--open <path>`; a running app receives it (single instance) and the
//! portal goes there.

/// Entries of the jump list: (title, portal path).
pub fn tasks(texts: &serde_json::Value) -> Vec<(String, String)> {
    let label = |key: &str, fallback: &str| {
        texts
            .get(key)
            .and_then(serde_json::Value::as_str)
            .unwrap_or(fallback)
            .to_string()
    };
    vec![
        (label("jumpChat", "Chat"), "/chat".into()),
        (label("jumpCalendar", "Calendar"), "/calendar".into()),
        (label("jumpMeetings", "Meetings"), "/meetings".into()),
        (label("jumpActivity", "Activity"), "/activity".into()),
    ]
}

/// The path from `--open <path>` on the command line, if it is one of the portal's own (starts with "/").
pub fn path_from_args(args: &[String]) -> Option<String> {
    let at = args.iter().position(|a| a == "--open")?;
    let path = args.get(at + 1)?;
    (path.starts_with('/') && !path.starts_with("//")).then(|| path.clone())
}

#[cfg(windows)]
#[allow(unsafe_code)]
pub fn install(tasks: &[(String, String)]) -> windows::core::Result<()> {
    use windows::core::{Interface, HSTRING, PWSTR};
    use windows::Win32::Storage::EnhancedStorage::PKEY_Title;
    use windows::Win32::System::Com::StructuredStorage::{
        PROPVARIANT, PROPVARIANT_0, PROPVARIANT_0_0, PROPVARIANT_0_0_0,
    };
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED,
    };
    use windows::Win32::System::Variant::VT_LPWSTR;
    use windows::Win32::UI::Shell::Common::{IObjectArray, IObjectCollection};
    use windows::Win32::UI::Shell::PropertiesSystem::IPropertyStore;
    use windows::Win32::UI::Shell::{
        DestinationList, EnumerableObjectCollection, ICustomDestinationList, IShellLinkW,
        ShellLink,
    };

    let exe = std::env::current_exe().map_err(|_| windows::core::Error::from_win32())?;
    let exe = HSTRING::from(exe.as_os_str());
    // SAFETY: COM calls with interfaces we created here; the title buffer outlives SetValue, which copies it
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let list: ICustomDestinationList =
            CoCreateInstance(&DestinationList, None, CLSCTX_INPROC_SERVER)?;
        let mut slots = 0u32;
        let _removed: IObjectArray = list.BeginList(&mut slots)?;
        let collection: IObjectCollection =
            CoCreateInstance(&EnumerableObjectCollection, None, CLSCTX_INPROC_SERVER)?;
        for (title, path) in tasks {
            let link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)?;
            link.SetPath(&exe)?;
            link.SetArguments(&HSTRING::from(format!("--open {path}")))?;
            link.SetIconLocation(&exe, 0)?;
            let mut wide: Vec<u16> = title.encode_utf16().chain(std::iter::once(0)).collect();
            let value = PROPVARIANT {
                Anonymous: PROPVARIANT_0 {
                    Anonymous: core::mem::ManuallyDrop::new(PROPVARIANT_0_0 {
                        vt: VT_LPWSTR,
                        wReserved1: 0,
                        wReserved2: 0,
                        wReserved3: 0,
                        Anonymous: PROPVARIANT_0_0_0 {
                            pwszVal: PWSTR(wide.as_mut_ptr()),
                        },
                    }),
                },
            };
            let store: IPropertyStore = link.cast()?;
            store.SetValue(&PKEY_Title, &value)?;
            store.Commit()?;
            // Not PropVariantClear: the text belongs to `wide`, not to COM
            std::mem::forget(value);
            collection.AddObject(&link)?;
        }
        let array: IObjectArray = collection.cast()?;
        list.AddUserTasks(&array)?;
        list.CommitList()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn open_argument_only_takes_portal_paths() {
        let args = |a: &[&str]| a.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert_eq!(path_from_args(&args(&["app.exe", "--open", "/chat"])), Some("/chat".into()));
        assert_eq!(path_from_args(&args(&["app.exe", "--open", "https://evil.example"])), None);
        assert_eq!(path_from_args(&args(&["app.exe", "--open", "//evil.example"])), None);
        assert_eq!(path_from_args(&args(&["app.exe", "--open"])), None);
        assert_eq!(path_from_args(&args(&["app.exe", "--hidden"])), None);
    }

    #[test]
    fn tasks_use_the_texts() {
        let texts = serde_json::json!({ "jumpChat": "Chat", "jumpCalendar": "Kalender" });
        let t = tasks(&texts);
        assert_eq!(t[1], ("Kalender".to_string(), "/calendar".to_string()));
        assert_eq!(t[2].0, "Meetings");
    }
}
