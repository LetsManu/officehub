//! The few texts of the app itself (address screen, ringing window, tray menu) in German or English, like the
//! system. Everything else comes from the portal in the person's language.

use serde_json::{json, Value};

fn german() -> bool {
    let lang = std::env::var("LANG").unwrap_or_default();
    if lang.starts_with("de") {
        return true;
    }
    #[cfg(windows)]
    {
        // The Windows display language (LANGID primary language 0x07 = German)
        extern "system" {
            fn GetUserDefaultUILanguage() -> u16;
        }
        // SAFETY: a plain Windows API call without arguments
        #[allow(unsafe_code)]
        let id = unsafe { GetUserDefaultUILanguage() };
        return id & 0x3ff == 0x07;
    }
    #[allow(unreachable_code)]
    false
}

pub fn for_system() -> Value {
    if german() {
        json!({
            "lang": "de",
            "connectTitle": "Willkommen bei OfficeHub",
            "connectText": "Gib die Adresse eures OfficeHub ein – so, wie du sie im Browser öffnest.",
            "addressLabel": "Adresse",
            "addressPlaceholder": "portal.firma.de",
            "connect": "Verbinden",
            "checking": "Wird geprüft …",
            "empty": "Bitte gib die Adresse ein.",
            "invalid": "Das sieht nicht wie eine Adresse aus.",
            "unreachable": "Unter dieser Adresse antwortet nichts. Stimmt sie, und bist du im Firmennetz?",
            "not_officehub": "Unter dieser Adresse läuft kein OfficeHub.",
            "trayOpen": "OfficeHub öffnen",
            "trayAutostart": "Mit Windows starten",
            "trayServer": "Mit anderem OfficeHub verbinden …",
            "trayQuit": "Beenden",
            "trayStatus": "Status",
            "statusAuto": "Automatisch",
            "statusAvailable": "Verfügbar",
            "statusBusy": "Beschäftigt",
            "statusDnd": "Nicht stören",
            "statusAway": "Bin gleich zurück",
            "statusOffline": "Als offline anzeigen",
            "jumpChat": "Chat",
            "jumpCalendar": "Kalender",
            "jumpMeetings": "Besprechungen",
            "jumpActivity": "Aktivität",
            "syncOpen": "OfficeHub-Ordner öffnen",
            "syncPauseMenu": "Synchronisierung anhalten",
            "syncSyncing": "Dateien werden abgeglichen …",
            "syncUpToDate": "Dateien sind aktuell",
            "syncOffline": "Keine Verbindung – Änderungen werden später abgeglichen",
            "syncSignIn": "Bitte in OfficeHub anmelden, damit der Ordner weiter abgleicht",
            "syncPaused": "Abgleich angehalten",
            "syncConflictWord": "Konflikt",
            "syncConflictTitle": "Zwei Versionen gespeichert",
            "syncConflictBody": "„{name}“ wurde gleichzeitig woanders geändert. Deine Version liegt daneben als „{copy}“.",
            "syncUnsupportedTitle": "Datei bleibt nur auf diesem PC",
            "syncUnsupportedBody": "„{name}“ kann nicht in OfficeHub gespeichert werden (Dateityp oder Größe).",
            "syncBusyTitle": "Datei ist gerade gesperrt",
            "syncBusyBody": "„{name}“ ist ausgecheckt oder wird gerade bearbeitet. Deine Änderung wird später gespeichert.",
            "syncDeletesTitle": "Dateien wiederhergestellt",
            "syncDeletesBody": "{count} Dateien und Ordner wurden auf einmal gelöscht. Sicherheitshalber wurden sie wiederhergestellt – löschen bitte im Portal.",
            "syncNewSpaceTitle": "Neue Bereiche im Portal anlegen",
            "syncNewSpaceBody": "Der Ordner „{name}“ ist kein Bereich und wird nicht abgeglichen. Lege neue Bereiche in OfficeHub an.",
            "syncOutsideTitle": "Datei in einen Bereich legen",
            "syncOutsideBody": "„{name}“ liegt direkt im OfficeHub-Ordner und wird nicht hochgeladen. Leg sie in den Ordner eines Bereichs.",
            "syncReadOnlyTitle": "Bereich ist schreibgeschützt",
            "syncReadOnlyBody": "„{name}“ bleibt nur auf diesem PC: In diesem Bereich darfst du nichts ändern (oder er ist archiviert).",
            "syncTooLargeTitle": "Datei ist zu groß",
            "syncTooLargeBody": "„{name}“ ist größer, als OfficeHub erlaubt, und bleibt nur auf diesem PC.",
            "syncFailedTitle": "Hochladen hat nicht geklappt",
            "syncFailedBody": "„{name}“ konnte nicht hochgeladen werden. OfficeHub versucht es später noch einmal.",
            "hiddenTitle": "OfficeHub läuft weiter",
            "hiddenBody": "Du bekommst weiter Nachrichten und Anrufe. Öffnen und Beenden über das Symbol unten rechts."
        })
    } else {
        json!({
            "lang": "en",
            "connectTitle": "Welcome to OfficeHub",
            "connectText": "Enter the address of your OfficeHub – the way you open it in the browser.",
            "addressLabel": "Address",
            "addressPlaceholder": "portal.company.com",
            "connect": "Connect",
            "checking": "Checking …",
            "empty": "Please enter the address.",
            "invalid": "That does not look like an address.",
            "unreachable": "Nothing answers at this address. Is it right, and are you on the company network?",
            "not_officehub": "There is no OfficeHub at this address.",
            "trayOpen": "Open OfficeHub",
            "trayAutostart": "Start with Windows",
            "trayServer": "Connect to another OfficeHub …",
            "trayQuit": "Quit",
            "trayStatus": "Status",
            "statusAuto": "Automatic",
            "statusAvailable": "Available",
            "statusBusy": "Busy",
            "statusDnd": "Do not disturb",
            "statusAway": "Be right back",
            "statusOffline": "Appear offline",
            "jumpChat": "Chat",
            "jumpCalendar": "Calendar",
            "jumpMeetings": "Meetings",
            "jumpActivity": "Activity",
            "syncOpen": "Open OfficeHub folder",
            "syncPauseMenu": "Pause syncing",
            "syncSyncing": "Syncing files …",
            "syncUpToDate": "Files are up to date",
            "syncOffline": "No connection – changes will sync later",
            "syncSignIn": "Please sign in to OfficeHub so the folder keeps syncing",
            "syncPaused": "Syncing paused",
            "syncConflictWord": "conflict",
            "syncConflictTitle": "Two versions kept",
            "syncConflictBody": "\"{name}\" was changed elsewhere at the same time. Your version is next to it as \"{copy}\".",
            "syncUnsupportedTitle": "File stays on this PC only",
            "syncUnsupportedBody": "\"{name}\" cannot be stored in OfficeHub (file type or size).",
            "syncBusyTitle": "File is locked right now",
            "syncBusyBody": "\"{name}\" is checked out or being edited. Your change will be saved later.",
            "syncDeletesTitle": "Files restored",
            "syncDeletesBody": "{count} files and folders were deleted at once. To be safe they were restored – please delete them in the portal.",
            "syncNewSpaceTitle": "Create new spaces in the portal",
            "syncNewSpaceBody": "The folder \"{name}\" is not a space and does not sync. Create new spaces in OfficeHub.",
            "syncOutsideTitle": "Put the file into a space",
            "syncOutsideBody": "\"{name}\" is right in the OfficeHub folder and is not uploaded. Move it into a space's folder.",
            "syncReadOnlyTitle": "This space is read only",
            "syncReadOnlyBody": "\"{name}\" stays only on this PC: you may not change this space (or it is archived).",
            "syncTooLargeTitle": "File too large",
            "syncTooLargeBody": "\"{name}\" is larger than OfficeHub allows and stays only on this PC.",
            "syncFailedTitle": "Upload did not work",
            "syncFailedBody": "\"{name}\" could not be uploaded. OfficeHub tries again later.",
            "hiddenTitle": "OfficeHub keeps running",
            "hiddenBody": "You still get messages and calls. Open or quit it from the icon at the bottom right."
        })
    }
}
