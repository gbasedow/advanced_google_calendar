# Advanced Google Calendar für Home Assistant

Custom-Integration, die Google-Kalender als `calendar.*`-Entitäten in Home Assistant abbildet und **in beide Richtungen** synchronisiert.

## Funktionen

- **Mehrere Google-Konten**: Jedes Konto ist ein eigener Konfigurationseintrag (eigener OAuth-Login; die Kalender stehen als Entitäten direkt unter dem Eintrag und heißen in der Kalenderansicht genau wie ihre Entität).
- **Kalenderauswahl per Checkbox**: Beim Einrichten und später über *Konfigurieren* lässt sich die Synchronisation für jeden Kalender (eigene, geteilte, abonnierte) einzeln ein- und ausschalten.
- **Google → Home Assistant**: Der Zustand der Entität (aktueller bzw. nächster Termin) wird im einstellbaren Intervall (1–60 min, Standard 5 min) aktualisiert. Die Kalenderansicht im Dashboard liest den angezeigten Zeitraum immer direkt bei Google.
- **Home Assistant → Google**: Termine **anlegen, ändern und löschen**, über die Kalenderansicht in HA, über `calendar.create_event` oder über die zusätzlichen Aktionen dieser Integration.
- **Serientermine**: „Nur dieser Termin“ und „Dieser und alle folgenden Termine“ funktionieren beim Ändern und beim Löschen. Beim Aufteilen einer Serie bleiben Farbe, Erinnerungen und Sichtbarkeit erhalten.
- **Kalender spiegeln (einseitig)**: Aktion `sync_calendar` überträgt einen beliebigen HA-Kalender in einen Google-Kalender, mit Zeitraum, Optionen und Regex-Filtern. Geänderte Optionen werden auf bestehende Abbilder angewendet.
- **Nur-Lese-Kalender** (z. B. Feiertage) werden angezeigt, bieten aber keine Schreibfunktionen an.
- **Reauth**: Ist der Zugriff abgelaufen oder widerrufen, meldet HA eine erneute Anmeldung. Dabei wird geprüft, dass dasselbe Konto verwendet wird.
- Keine zusätzlichen Python-Abhängigkeiten: Die Integration spricht direkt mit der Google Calendar API v3.

Voraussetzung: Home Assistant **2025.10** oder neuer.

## Installation & Einrichtung

👉 **Ausführliche Schritt-für-Schritt-Anleitung inkl. Google-Cloud-Vorbereitung: [docs/ANLEITUNG.md](docs/ANLEITUNG.md)**

Kurzfassung:
1. Google Cloud: Projekt anlegen, *Google Calendar API* aktivieren, OAuth-Zustimmungsbildschirm (extern, **in Produktion**) einrichten, OAuth-Client vom Typ *Webanwendung* mit der Weiterleitungs-URI `https://my.home-assistant.io/redirect/oauth` erstellen.
2. Integration per HACS (benutzerdefiniertes Repository) oder manuell nach `config/custom_components/advanced_google_calendar` kopieren und HA neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Advanced Google Calendar*, Client-ID und Clientschlüssel eingeben, mit Google anmelden und die Kalender auswählen.
4. Für jedes weitere Google-Konto Schritt 3 wiederholen.

## Aktionen (Services)

| Aktion | Zweck |
|---|---|
| `calendar.create_event` | Termin anlegen (Standardaktion von HA) |
| `advanced_google_calendar.list_events` | Termine inkl. `uid`, `recurrence_id`, `rrule` abrufen (mit Rückgabewert) |
| `advanced_google_calendar.update_event` | Termin ändern; nur die angegebenen Felder werden geändert |
| `advanced_google_calendar.delete_event` | Termin, einzelnen Serientermin oder „diesen und folgende“ löschen |
| `advanced_google_calendar.sync_calendar` | Einen beliebigen Kalender einseitig in einen Google-Kalender spiegeln (Zeitraum in Tagen, Details ja/nein, Ganztägige ja/nein, Regex-Filter auf den Titel, Probelauf) |

Beispiele findest du in der [Anleitung](docs/ANLEITUNG.md#7-nutzung-in-dashboard-und-automationen).

## Entwicklung / Tests

```bash
pip install -r requirements_test.txt
```

```bash
pytest
```
