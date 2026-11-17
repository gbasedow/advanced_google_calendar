# Anleitung: Advanced Google Calendar einrichten

Diese Anleitung führt dich Schritt für Schritt durch die Einrichtung, vom leeren Google-Cloud-Projekt bis zum synchronisierten Kalender in Home Assistant.

**Inhalt**

1. [Überblick: Was wird eingerichtet?](#1-überblick-was-wird-eingerichtet)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Google Cloud vorbereiten](#3-google-cloud-vorbereiten)
4. [Integration installieren](#4-integration-installieren)
5. [Integration in Home Assistant einrichten](#5-integration-in-home-assistant-einrichten)
6. [Weitere Konten, Kalender an-/abwählen, Intervall](#6-weitere-konten-kalender-an-abwählen-intervall)
7. [Nutzung in Dashboard und Automationen](#7-nutzung-in-dashboard-und-automationen)
8. [So funktioniert die Synchronisation](#8-so-funktioniert-die-synchronisation)
9. [Fehlerbehebung](#9-fehlerbehebung)
10. [Sicherheit, Zugriff widerrufen, Deinstallation](#10-sicherheit-zugriff-widerrufen-deinstallation)

---

## 1. Überblick: Was wird eingerichtet?

```
Google-Konto A ──┐                                   ┌─ calendar.konto_a_privat
Google-Konto B ──┼─► OAuth-Client (dein Google-Cloud-Projekt) ─► HA ─┼─ calendar.konto_a_familie
                 │                                   └─ calendar.konto_b_arbeit
```

- In der **Google Cloud** legst du *einmalig* ein Projekt mit einem OAuth-Client an. Diesen einen Client nutzen alle Google-Konten, die du einbinden willst.
- In **Home Assistant** hinterlegst du Client-ID und Clientschlüssel *einmalig* als „Anwendungsanmeldeinformationen“.
- Danach fügst du die Integration **pro Google-Konto einmal** hinzu und wählst jeweils die Kalender aus.

Zeitaufwand: ca. 15–20 Minuten.

## 2. Voraussetzungen

- Home Assistant **2025.10 oder neuer**.
- Ein Google-Konto für die Google Cloud Console. Das kann eines der Konten sein, deren Kalender du einbinden willst, muss es aber nicht.
- Die Integration **My Home Assistant** ist aktiv. Sie ist Teil von `default_config:` und damit in praktisch jeder Installation aktiv. Falls du `default_config:` entfernt hast, ergänze in der `configuration.yaml` die Zeile `my:` und starte HA neu.
- Der Browser, mit dem du die Einrichtung durchführst, muss Home Assistant erreichen können (lokal reicht). Eine externe URL oder Nabu Casa ist **nicht** nötig.

## 3. Google Cloud vorbereiten

> Die Google Cloud Console wird regelmäßig umgestaltet. Die Menübezeichnungen unten entsprechen dem Stand Ende 2026 (deutsche Oberfläche). Englische Bezeichnungen stehen in Klammern.

### 3.1 Projekt anlegen

1. Öffne <https://console.cloud.google.com/> und melde dich an.
2. Klicke oben links neben dem Google-Cloud-Logo auf die **Projektauswahl** und dann auf **Neues Projekt** (*New project*).
3. Projektname, z. B. `Home Assistant Kalender`. Organisation/Speicherort: „Keine Organisation“ ist für private Konten richtig.
4. **Erstellen** klicken, kurz warten und sicherstellen, dass oben das neue Projekt ausgewählt ist.

> Es fallen keine Kosten an. Die Calendar API ist kostenlos, ein Rechnungskonto ist nicht nötig.

### 3.2 Google Calendar API aktivieren

1. Menü ☰ → **APIs & Dienste** → **Bibliothek** (*APIs & Services → Library*).
2. Nach **Google Calendar API** suchen und den Eintrag öffnen.
3. **Aktivieren** (*Enable*) klicken.

### 3.3 OAuth-Zustimmungsbildschirm (Google Auth Platform) einrichten

1. Menü ☰ → **Google Auth Platform** (oder *APIs & Dienste → OAuth-Zustimmungsbildschirm*). Falls angezeigt: **Jetzt starten** (*Get started*).
2. **App-Informationen**
   - *App-Name*: z. B. `Home Assistant`. Dieser Name erscheint später im Google-Login.
   - *Nutzersupport-E-Mail*: deine E-Mail-Adresse.
   - **Weiter**.
3. **Zielgruppe** (*Audience*): **Extern** (*External*) wählen. „Intern“ gibt es nur für Google-Workspace-Organisationen. **Weiter**.
4. **Kontaktdaten**: deine E-Mail-Adresse. **Weiter**.
5. Den Richtlinien zustimmen und **Erstellen** klicken.

#### Datenzugriff (Bereich/Scope) hinterlegen

6. Links **Datenzugriff** (*Data Access*) → **Bereiche hinzufügen oder entfernen** (*Add or remove scopes*).
7. In der Liste nach `calendar` filtern und den Bereich
   `https://www.googleapis.com/auth/calendar`
   („Alle Kalender, auf die Sie über Google Kalender zugreifen können, ansehen, bearbeiten, teilen und dauerhaft löschen“) anhaken.
   Ist er nicht in der Liste, trägst du ihn unten unter **Bereiche manuell hinzufügen** ein.
8. **Aktualisieren** und anschließend **Speichern**.

> Dieser Bereich ist nötig, weil die Integration Termine anlegen, ändern und löschen soll und die Kalenderliste lesen muss.

#### Veröffentlichungsstatus: wichtig!

9. Links **Zielgruppe** (*Audience*). Der Status steht zunächst auf **Testen** (*Testing*).
10. Klicke auf **App veröffentlichen** (*Publish app*) und bestätige. Der Status ist danach **In Produktion** (*In production*).

> **Warum?** Im Status *Testen* laufen die Anmeldungen (Refresh-Tokens) **nach 7 Tagen ab**. Home Assistant würde dich dann jede Woche zur erneuten Anmeldung auffordern.
>
> „In Produktion“ heißt hier **nicht**, dass die App öffentlich gelistet wird. Ohne Google-Überprüfung sieht jeder Nutzer beim Login den Hinweis „Google hat diese App nicht überprüft“, und es sind höchstens 100 Konten möglich. Für den privaten Gebrauch ist das unproblematisch, eine Verifizierung ist **nicht** nötig.
>
> *Alternative (nicht empfohlen):* Status *Testen* belassen und unter **Testnutzer** (*Test users*) jedes Google-Konto eintragen, dessen Kalender du einbinden willst. Dann ist alle 7 Tage eine erneute Anmeldung nötig.

### 3.4 OAuth-Client erstellen

1. Links **Clients** → **Client erstellen** (*Create client*).
   (Alternativ: *APIs & Dienste → Anmeldedaten → Anmeldedaten erstellen → OAuth-Client-ID*.)
2. **Anwendungstyp**: **Webanwendung** (*Web application*).
3. **Name**: z. B. `Home Assistant`.
4. **Autorisierte JavaScript-Quellen**: leer lassen.
5. **Autorisierte Weiterleitungs-URIs** → **URI hinzufügen** und exakt eintragen:

   ```
   https://my.home-assistant.io/redirect/oauth
   ```

6. **Erstellen** klicken.
7. Es erscheinen **Client-ID** und **Clientschlüssel** (*Client secret*).
   **Kopiere beide sofort** oder lade die JSON-Datei herunter. Google zeigt den Clientschlüssel inzwischen nur bei der Erstellung vollständig an. Fehlt er später, kannst du in den Client-Details einen neuen Schlüssel hinzufügen.

> **Ohne My Home Assistant:** Ist die `my`-Integration deaktiviert, verwendet HA stattdessen `https://<deine-externe-HA-Adresse>/auth/external/callback` (externe URL unter *Einstellungen → System → Netzwerk*). Google akzeptiert dort nur öffentliche HTTPS-Domains (oder `localhost`), keine lokalen IP-Adressen. Diese URI muss dann zusätzlich als Weiterleitungs-URI eingetragen werden.

Damit ist die Google-Seite fertig.

## 4. Integration installieren

### Variante A: HACS (empfohlen)

1. In HA **HACS** öffnen → oben rechts **⋮** → **Benutzerdefinierte Repositories**.
2. Repository: `https://github.com/gbasedow/advanced_google_calendar`, Typ: **Integration** → **Hinzufügen**.
3. In HACS nach **Advanced Google Calendar** suchen → **Herunterladen**.
4. Home Assistant **neu starten** (*Einstellungen → System → ⏻ → Home Assistant neu starten*).

### Variante B: manuell

1. Den Ordner `custom_components/advanced_google_calendar` aus diesem Repository nach
   `/config/custom_components/advanced_google_calendar` kopieren (z. B. mit dem Add-on *File editor*, *Samba* oder *SSH*).
   Danach muss z. B. die Datei `/config/custom_components/advanced_google_calendar/manifest.json` existieren.
2. Home Assistant **neu starten**.

## 5. Integration in Home Assistant einrichten

### 5.1 Anwendungsanmeldeinformationen hinterlegen

Das geht entweder vorab oder automatisch beim ersten Hinzufügen der Integration (Schritt 5.2 fragt danach, wenn noch nichts hinterlegt ist).

Vorab:
1. **Einstellungen → Geräte & Dienste** → oben rechts **⋮** → **Anwendungsanmeldeinformationen**.
2. **Anmeldedaten hinzufügen**:
   - *Integration*: **Advanced Google Calendar**
   - *Name*: z. B. `Google`
   - *OAuth-Client-ID* und *OAuth-Clientschlüssel* aus Schritt 3.4
3. **Hinzufügen**.

### 5.2 Erstes Google-Konto verbinden

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → nach **Advanced Google Calendar** suchen.
2. Es öffnet sich ein neues Fenster/Tab mit dem Google-Login:
   1. **Konto auswählen**, dessen Kalender eingebunden werden sollen.
   2. Hinweis „**Google hat diese App nicht überprüft**“: auf **Erweitert** und dann **Zu Home Assistant wechseln (unsicher)** klicken. Das ist deine eigene App aus Schritt 3.
   3. Auf der Berechtigungsseite den Zugriff auf **Google Kalender** erlauben. Falls Google Kontrollkästchen anzeigt, **muss das Häkchen beim Kalenderzugriff gesetzt sein**, sonst schlägt das Laden der Kalender fehl.
   4. **Weiter**.
3. Du landest auf **my.home-assistant.io**. Beim allerersten Mal fragt die Seite nach der Adresse deiner HA-Instanz (z. B. `http://homeassistant.local:8123`). Danach **Konto verknüpfen** (*Link account*) klicken. Das Fenster schließt sich bzw. leitet zurück zu HA.
4. In HA erscheint der Dialog **Kalender auswählen**:
   - Alle Kalender des Kontos werden als Checkboxen angezeigt (eigene, geteilte, abonnierte, ausgeblendete). Kalender mit 🔒 sind **nur lesbar** und können in HA nicht bearbeitet werden.
   - Der Hauptkalender ist vorausgewählt. Hake alle Kalender an, die synchronisiert werden sollen (mindestens einen).
   - **Abfrageintervall**: wie oft Änderungen aus Google abgeholt werden (1–60 Minuten, Standard 5).
5. **Absenden**. Das Konto erscheint als Konfigurationseintrag mit der E-Mail-Adresse als Titel. Darunter steht jeder gewählte Kalender direkt als Entität `calendar.<kalendername>`, z. B. `calendar.privat`. Ein Gerät wird bewusst nicht angelegt, sonst würde die Kalenderansicht den Gerätenamen vor jeden Kalender setzen.
   In der Kalenderansicht („Meine Kalender“) und überall sonst heißt der Kalender wie seine Entität, ohne Präfix. Der Hauptkalender heißt bei Google standardmäßig wie die E-Mail-Adresse. Haben zwei Konten einen gleichnamigen Kalender, hängt HA an die Entitäts-ID `_2` an. Den angezeigten Namen kannst du in den Entitätseinstellungen jederzeit ändern.

## 6. Weitere Konten, Kalender an-/abwählen, Intervall

### Weiteres Google-Konto hinzufügen

Einfach Schritt **5.2 erneut** ausführen und im Google-Login das **andere Konto** wählen. Die Kontoauswahl erscheint immer. Die Anwendungsanmeldeinformationen werden wiederverwendet.
Wird ein Konto gewählt, das bereits eingerichtet ist, bricht der Dialog mit „Dieses Google-Konto ist bereits eingerichtet“ ab.

> Läuft deine App noch im Status *Testen*, muss jedes Konto als **Testnutzer** eingetragen sein (siehe 3.3).

### Kalender später an- oder abwählen

1. **Einstellungen → Geräte & Dienste → Advanced Google Calendar**.
2. Beim gewünschten Konto auf **Konfigurieren** (⚙) klicken.
3. Die Kalenderliste wird frisch von Google geladen, neue Kalender erscheinen also automatisch. Häkchen setzen oder entfernen, ggf. das Intervall ändern → **Absenden**.
4. Die Integration lädt neu: Neu gewählte Kalender bekommen eine Entität, **abgewählte Kalender werden samt Entität entfernt**. In Google selbst wird dabei nichts gelöscht.

### Erneute Anmeldung (Reauth)

Wurde der Zugriff widerrufen, das Passwort geändert oder ist das Token abgelaufen, zeigt HA unter *Einstellungen → Geräte & Dienste* den Hinweis, dass eine erneute Authentifizierung nötig ist. Klicke dort auf **Erneut konfigurieren** und melde dich mit **demselben** Google-Konto an. Bei einem anderen Konto bricht der Vorgang mit einem Hinweis ab.

## 7. Nutzung in Dashboard und Automationen

### Dashboard / Kalenderansicht

In der Seitenleiste unter **Kalender** (oder mit der Kalender-Karte) siehst du alle Termine.
- **Anlegen**: Button **+ Termin hinzufügen** und den Google-Kalender wählen.
- **Ändern/Löschen**: Termin anklicken → **Bearbeiten** bzw. **Löschen**.
- Bei **Serienterminen** fragt HA, ob nur **dieser Termin** oder **dieser und alle folgenden** geändert/gelöscht werden sollen. Beides wird in Google genauso umgesetzt.

### Termin anlegen

```yaml
action: calendar.create_event
target:
  entity_id: calendar.privat
data:
  summary: "MTB-Runde"
  description: "Treffpunkt Parkplatz"
  location: "Wanderparkplatz am Waldrand"
  start_date_time: "2026-11-21 09:00:00"
  end_date_time: "2026-11-21 12:00:00"
```

Ganztägig: `start_date: "2026-11-21"` und `end_date: "2026-11-22"` (das Enddatum ist exklusiv).

### Termine mit IDs abrufen

Die HA-Standardaktion `calendar.get_events` liefert keine IDs. Zum Ändern oder Löschen per Automation gibt es deshalb:

```yaml
action: advanced_google_calendar.list_events
target:
  entity_id: calendar.privat
data:
  duration:
    days: 7
response_variable: termine
```

Ergebnis (gekürzt):

```yaml
calendar.privat:
  events:
    - uid: "5g1h2..."               # ID des Termins bzw. der Serie
      recurrence_id: "5g1h2..._20261124T170000Z"   # nur bei Serienterminen
      rrule: "FREQ=WEEKLY;BYDAY=TU"
      summary: "Training"
      start: "2026-11-24T18:00:00+01:00"
      end: "2026-11-24T19:30:00+01:00"
      all_day: false
```

### Termin ändern (nur angegebene Felder)

Beispiel: Beim nächsten Termin „Training“ den Ort ändern (nur dieses Vorkommen, falls es ein Serientermin ist):

```yaml
sequence:
  - action: advanced_google_calendar.list_events
    target:
      entity_id: calendar.privat
    data:
      duration:
        days: 14
    response_variable: termine
  - variables:
      treffer: >-
        {{ termine['calendar.privat'].events
           | selectattr('summary', 'eq', 'Training') | list }}
  - condition: template
    value_template: "{{ treffer | count > 0 }}"
  - action: advanced_google_calendar.update_event
    target:
      entity_id: calendar.privat
    data:
      uid: "{{ treffer[0].uid }}"
      recurrence_id: "{{ treffer[0].recurrence_id or '' }}"
      location: "Sporthalle Nord"
```

Mögliche Felder: `summary`, `description`, `location`, `start_date_time` + `end_date_time` **oder** `start_date` + `end_date`, `rrule`.

| `recurrence_id` | `recurrence_range` | Wirkung |
|---|---|---|
| leer | – | Einzeltermin bzw. **ganze Serie** ändern (Achtung: Start/Ende verschieben dann die ganze Serie) |
| gesetzt | leer | nur **dieses** Vorkommen |
| gesetzt | `THISANDFUTURE` | **dieses und alle folgenden** (es entsteht ab hier eine neue Serie) |

`rrule` ohne Präfix `RRULE:` angeben, z. B. `FREQ=WEEKLY;BYDAY=MO,WE`. Ein leerer Text `""` macht aus einer Serie einen Einzeltermin. Ohne `rrule` bleibt die Wiederholung unverändert.

### Termin löschen

```yaml
action: advanced_google_calendar.delete_event
target:
  entity_id: calendar.privat
data:
  uid: "{{ treffer[0].uid }}"
  recurrence_id: "{{ treffer[0].recurrence_id or '' }}"
  # recurrence_range: THISANDFUTURE   # optional: dieses und alle folgenden
```

### Kalender spiegeln (einseitig)

Mit `advanced_google_calendar.sync_calendar` überträgst du die Termine eines **Quellkalenders** in einen **Zielkalender**, und zwar nur in diese eine Richtung.
- **Quelle** (`source_entity_id`): **jeder** Kalender in Home Assistant, also auch ein Google-Kalender eines anderen Kontos, ein lokaler Kalender, CalDAV oder ein Müllabfuhrkalender. Die Quelle wird nur gelesen.
- **Ziel** (`target_entity_id`): ein beschreibbarer Google-Kalender dieser Integration.

In der Oberfläche (*Entwicklerwerkzeuge → Aktionen* oder im Automationseditor) wählst du beide Kalender oben per Auswahlliste aus. Jedes Feld der Maske ist dort beschrieben. Die beiden Filterfelder sind optional und haben deshalb eine Checkbox davor. Ohne Haken ist der jeweilige Filter aus.

```yaml
action: advanced_google_calendar.sync_calendar
data:
  source_entity_id: calendar.arbeit_firma_de_termine  # Quelle
  target_entity_id: calendar.familie    # Ziel (Abbild)
  days_past: 7          # Tage in die Vergangenheit (0–365, Standard 7)
  days_future: 60       # Tage in die Zukunft (0–730, Standard 30)
  include_description: true # Beschreibung mitkopieren (Standard true)
  include_location: true    # Ort mitkopieren (Standard true)
  include_all_day: true # ganztägige Termine mitkopieren (Standard true)
  # include_regex: "training|jagd"  # optional; weglassen/leer = alle Termine
  exclude_regex: "privat|arzt"      # optional; weglassen/leer = nichts ausschließen
  dry_run: false        # true = nur anzeigen, nichts schreiben
response_variable: ergebnis
```

| Parameter | Bedeutung |
|---|---|
| `days_past` / `days_future` | Pflichtfelder. Zeitraum ab dem heutigen Tag (ganze Tage). **Beide 0 = nur die Termine von heute.** Termine **außerhalb** des Zeitraums werden im Ziel nicht verändert, auch keine alten Abbilder. |
| `include_description` | `false`: Die Beschreibung wird nicht übernommen und in den Kopien im Zielkalender **gelöscht**, auch bei bereits gespiegelten Terminen. |
| `include_location` | `false`: Der Ort wird nicht übernommen und in den Kopien im Zielkalender **gelöscht**, auch bei bereits gespiegelten Terminen. |
| `include_details` | Veraltet, nur noch für ältere Automationen: setzt `include_description` und `include_location` gemeinsam. Ein ausdrücklich angegebenes neues Feld hat Vorrang. |
| `include_all_day` | `false`: ganztägige Termine werden nicht gespiegelt. |
| `include_regex` | Optional. **Leer bzw. nicht gesetzt = alle Termine werden synchronisiert.** Sonst regulärer Ausdruck auf den **Titel**. Nur passende Termine werden gespiegelt. Groß-/Kleinschreibung spielt keine Rolle, der Ausdruck muss nur irgendwo im Titel vorkommen (`training` passt auf „MTB-Training“). Für einen exakten Titel: `^Training$`. |
| `exclude_regex` | Optional. Leer bzw. nicht gesetzt = nichts wird ausgeschlossen. Sonst regulärer Ausdruck auf den Titel. Passende Termine werden **nicht** gespiegelt. **Sind beide Felder belegt, hat das Ausschließen Vorrang:** Ein Termin, der auf beide Ausdrücke passt, wird nicht synchronisiert. |
| `dry_run` | `true`: nichts schreiben, nur zurückgeben, was angelegt, geändert und gelöscht würde (Listen `to_create`, `to_update`, `to_delete`). Ideal zum Testen der regulären Ausdrücke. |

**Verhalten**
- Neue Termine der Quelle werden angelegt, geänderte aktualisiert, gelöschte (oder nicht mehr passende) im Ziel gelöscht.
- **Geänderte Optionen wirken auf bereits gespiegelte Termine.** Schaltest du z. B. `include_description` aus, wird beim nächsten Lauf die Beschreibung aus allen vorhandenen Abbildern entfernt, der Ort bleibt erhalten (und umgekehrt mit `include_location`). Bei `include_all_day: false` oder einem geänderten Ausdruck werden nicht mehr passende Abbilder gelöscht und neu passende angelegt.
- Im Zielkalender werden **nur Termine angefasst, die diese Synchronisation selbst angelegt hat**. Dafür trägt jedes Abbild eine unsichtbare Markierung. Deine eigenen Termine im Zielkalender bleiben unberührt. Mehrere Quellen können in denselben Zielkalender gespiegelt werden.
- Serientermine werden als einzelne Termine gespiegelt.
- Abbilder haben keine Erinnerungen. So bekommst du keine doppelten Benachrichtigungen.
- Termine, die selbst ein Abbild sind, werden nicht weitergespiegelt. Ist die Quelle ein Google-Kalender dieser Integration, entsteht dadurch auch bei A→B und B→A keine Endlosschleife.
- Rückgabe: `created`, `updated`, `deleted`, `unchanged` und `errors`. Scheitert ein einzelner Termin (z. B. wegen eines API-Limits), läuft der Rest weiter, und der Fehler steht in `errors`.
- Die Quelle wird über ihre interne Registry-ID zugeordnet. Benennst du die Quell-Entität um, bleiben die vorhandenen Abbilder daher erhalten.

**Regelmäßig ausführen**: Die Aktion läuft nur, wenn sie aufgerufen wird. Für eine laufende Spiegelung eine Automation anlegen, z. B. alle 15 Minuten:

```yaml
alias: Arbeitskalender in Familienkalender spiegeln
mode: single
triggers:
  - trigger: time_pattern
    minutes: "/15"
actions:
  - action: advanced_google_calendar.sync_calendar
    data:
      source_entity_id: calendar.arbeit_firma_de_termine
      target_entity_id: calendar.familie
      days_past: 1
      days_future: 60
      include_description: false
      include_location: true
      exclude_regex: "privat"
```

> **Tipp:** Wechselst du zwischen zwei Konfigurationen (z. B. mit und ohne Details), passen sich die Abbilder bei jedem Lauf an die jeweils übergebenen Optionen an. Verwende für eine Quelle-Ziel-Kombination deshalb immer dieselben Parameter.

### Spiegelung entfernen

Rufe die Aktion mit einem Ausdruck auf, der nichts zulässt, z. B. `include_regex: "^$a"` (passt nie). Dann werden alle Abbilder dieser Quelle im Zeitraum gelöscht. Danach die Automation deaktivieren.

### Auf Termine reagieren (Kalender-Auslöser)

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.jagd
    offset: "-1:00:00"
actions:
  - action: notify.notify
    data:
      message: "In einer Stunde: {{ trigger.calendar_event.summary }}"
```

## 8. So funktioniert die Synchronisation

| Richtung | Wie |
|---|---|
| Google → HA (Entitätszustand, Attribute, Kalender-Auslöser) | Abfrage der nächsten Termine im eingestellten Intervall. Änderungen in Google sind spätestens nach diesem Intervall in HA sichtbar. |
| Google → HA (Kalenderansicht, `list_events`, `calendar.get_events`) | Wird bei jedem Aufruf direkt bei Google gelesen, ist also immer aktuell. |
| HA → Google (anlegen/ändern/löschen) | Sofortiger API-Aufruf. Danach aktualisiert sich die Entität direkt. |

Hinweise:
- Die Zeitzone neuer Termine ist die Zeitzone von Home Assistant (*Einstellungen → System → Allgemein*).
- Bei einer Änderung „dieser und alle folgenden“ legt die Integration zuerst die neue Serie an und kürzt danach die alte. Schlägt das Kürzen fehl, wird die neue Serie wieder entfernt, sodass keine Termine verloren gehen.
- Teilnehmer, Anhänge und Videokonferenzen werden von HA nicht bearbeitet und bleiben bei normalen Änderungen erhalten, weil nur die genannten Felder übertragen werden. Ausnahme: Bei „dieser und alle folgenden“ entsteht eine neue Serie. Sie übernimmt Titel, Beschreibung, Ort, Farbe, Erinnerungen und Sichtbarkeit, aber **keine Teilnehmer**, damit Google keine ungewollten Einladungen verschickt.
- Wiederholungsregeln, die HA nicht kennt (z. B. stündlich), werden angezeigt, ohne die Regel in HA darzustellen.

## 9. Fehlerbehebung

| Problem | Ursache / Lösung |
|---|---|
| Google meldet **„Fehler 400: redirect_uri_mismatch“** | Die Weiterleitungs-URI im OAuth-Client stimmt nicht. Exakt `https://my.home-assistant.io/redirect/oauth` eintragen (ohne Schrägstrich am Ende). Änderungen können einige Minuten dauern. |
| **„Fehler 403: access_denied“** / „App wird getestet“ | App steht auf *Testen* und das Konto ist kein Testnutzer → App veröffentlichen (3.3) oder Konto als Testnutzer eintragen. |
| **„Fehler 401: invalid_client“** | Client-ID/-Schlüssel falsch. Unter *Anwendungsanmeldeinformationen* löschen und neu anlegen. |
| Dialog bricht mit **„Verbindung zur Google Calendar API fehlgeschlagen“** ab | Calendar API nicht aktiviert (3.2) oder beim Login das Häkchen für den Kalenderzugriff nicht gesetzt. |
| Nach 7 Tagen erneute Anmeldung nötig | App steht auf *Testen* → veröffentlichen (3.3) und einmal neu anmelden. |
| **Konfigurieren** meldet „Die Integration muss geladen sein …“ | Der Eintrag ist nicht geladen (z. B. Anmeldung abgelaufen). Erst neu anmelden, dann konfigurieren. |
| Termin lässt sich nicht bearbeiten | Kalender ist nur lesbar (🔒, Rolle *reader*/*freeBusyReader*). Freigabe in Google auf „Änderungen vornehmen“ setzen und die Kalenderauswahl erneut speichern. |
| Änderung aus Google erscheint nicht sofort | Normal. Der Zustand folgt nach dem Abfrageintervall, die Kalenderansicht sofort beim Neuladen. |
| Fehlermeldung „Event not found“ | Der Termin wurde inzwischen in Google gelöscht oder geändert → Ansicht neu laden. |

**Debug-Logging** aktivieren (`configuration.yaml`, danach Neustart):

```yaml
logger:
  default: warning
  logs:
    custom_components.advanced_google_calendar: debug
```

Alternativ: *Einstellungen → Geräte & Dienste → Advanced Google Calendar → ⋮ → Debug-Protokollierung aktivieren*.

## 10. Sicherheit, Zugriff widerrufen, Deinstallation

- Die Tokens liegen ausschließlich in deiner HA-Instanz (`/config/.storage`). Behandle Backups daher vertraulich.
- Der Clientschlüssel gehört nur in HA, nicht in öffentliche Repositories oder Foren.
- **Zugriff widerrufen**: <https://myaccount.google.com/connections> → App „Home Assistant“ → Zugriff entfernen.
- **Konto aus HA entfernen**: *Einstellungen → Geräte & Dienste → Advanced Google Calendar →* beim Eintrag **⋮ → Löschen**. In Google wird dabei nichts gelöscht.
- **Deinstallation**: alle Einträge löschen, dann in HACS **Entfernen** (bzw. Ordner löschen) und HA neu starten. Optional die Anwendungsanmeldeinformationen und das Google-Cloud-Projekt löschen.
