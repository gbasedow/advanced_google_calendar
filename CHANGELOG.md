# Changelog

## 0.4.0 – 2026-11-16

- Kalender dieser Integration werden nur noch mit ihrem Kalendernamen angezeigt
  (z. B. „Privat“ statt „user@gmail.com Privat“), u. a. in der Kalenderansicht.
- Neu eingerichtete Kalender erhalten die Entitäts-ID `calendar.<kalendername>`.
  Bestehende Entitäts-IDs bleiben unverändert, Automationen müssen nicht
  angepasst werden. Selbst vergebene Namen bleiben erhalten.

## 0.3.0 – 2026-11-16

- Maske der Aktion `sync_calendar` überarbeitet:
  - Quellkalender steht an erster Stelle, der Zielkalender wird darunter ebenfalls
    per Auswahlliste gewählt (neues Feld `target_entity_id`).
  - `days_past` / `days_future` sind Pflichtfelder (Standard 7 / 30);
    beide 0 = nur die Termine von heute.
  - Keine Auswahl-Checkboxen mehr bei den Regex-Feldern und beim Probelauf;
    leere Regex-Felder bedeuten „kein Filter“.
  - Ausführliche Beschreibungen für alle Felder (Deutsch/Englisch).
- **Breaking Change:** Das Ziel wird nicht mehr über `target: entity_id:` angegeben,
  sondern über `target_entity_id`. Bestehende Automationen bitte anpassen.

## 0.2.0 – 2026-11-16

- Neue Aktion `advanced_google_calendar.sync_calendar`: spiegelt einen beliebigen
  Home-Assistant-Kalender einseitig in einen Google-Kalender dieser Integration.
  - Parameter `days_past` / `days_future` für den Zeitraum.
  - `include_details` (Beschreibung/Ort), `include_all_day` (ganztägige Termine),
    `include_regex` / `exclude_regex` (Filter auf den Titel), `dry_run`.
  - Geänderte Optionen werden beim nächsten Lauf auf bestehende Abbilder angewendet.
  - Nur selbst angelegte Abbilder werden geändert/gelöscht; Abbilder werden nicht
    weitergespiegelt (keine Schleifen), Abbilder ohne Erinnerungen.

## 0.1.0 – 2026-11-16

Erste Version.

- Google-Kalender als `calendar.*`-Entitäten mit Zwei-Wege-Synchronisation
  (Abfrage im einstellbaren Intervall, Anlegen/Ändern/Löschen in Google).
- Serientermine: „nur dieser“ und „dieser und alle folgenden“ beim Ändern und Löschen.
- Mehrere Google-Konten (ein Konfigurationseintrag pro Konto, OAuth2 über
  Anwendungsanmeldeinformationen).
- Kalenderauswahl per Checkbox beim Einrichten und über „Konfigurieren“.
- Erneute Anmeldung (Reauth) mit Prüfung auf dasselbe Konto.
- Aktionen `list_events`, `update_event`, `delete_event`.
- Übersetzungen Deutsch/Englisch, Schritt-für-Schritt-Anleitung (`docs/ANLEITUNG.md`).

Voraussetzung: Home Assistant 2025.10 oder neuer.
