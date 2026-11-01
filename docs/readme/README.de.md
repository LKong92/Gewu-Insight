# Gewu Insight

**Ein integrierter Forschungsarbeitsbereich für Literatursuche, Lesen, Projektorganisation und KI-Zusammenarbeit.**

Gewu Insight ist ein Desktop-Arbeitsbereich für Forschende, der Literatursuche, Organisation und Lesen verbindet. Preprints, veröffentlichte Fassungen, ergänzende Dateien und Notizen bleiben demselben Artikel zugeordnet – auch über mehrere Projekte hinweg. Optional kann ein KI-Assistent auf freigegebene Quellen und gespeicherte Analysen zugreifen, um die Arbeit später fortzusetzen.

[English](../../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · **Deutsch**

[**Für macOS herunterladen**](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.1.0) · [**Für Windows herunterladen**](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.1.0) · [**Produktvideo ansehen**](https://gewu-insight.com/product.html?lang=en#tour) · [Website](https://gewu-insight.com) · [Handbücher](https://gewu-insight.com/resources.html#resources)

**macOS 1.1.0 · Windows 1.1.0**. Dies ist eine deutschsprachige Einführung. Die App-Oberfläche und die ausführlichen Handbücher sind derzeit auf Englisch. Menübezeichnungen entsprechen deshalb der englischen Oberfläche.

## Gewu Insight im Video

**[▶ Überblick auf YouTube · Englisch · 1:18](https://www.youtube.com/watch?v=8-dK6H2t2gQ)** · [Video auf Bilibili · Chinesisch](https://www.bilibili.com/video/BV1tRxt68E7p/) · [Bebilderte Einführung auf Zhihu · Chinesisch](https://zhuanlan.zhihu.com/p/2100363950269506568)

Erfahren Sie, wie Literatursuche, Lesen, Projektorganisation, KI-Zusammenarbeit und Zotero-Integration in einem gemeinsamen Arbeitsbereich zusammenkommen.

### Ausführlicher Rundgang auf der Website

<!-- Original video cover: https://gewu-insight.com/assets/product-poster-en.jpg -->
<p align="center">
  <a href="https://gewu-insight.com/product.html?lang=en#tour"><img src="../../assets/readme/product-film-en.jpg" width="720" alt="▶ Auf Englisch ansehen · 5:19"></a>
</p>

**[▶ Auf Englisch ansehen · 5:19](https://gewu-insight.com/product.html?lang=en#tour)** · **[▶ Auf Chinesisch ansehen · 5:23](https://gewu-insight.com/product.html?lang=zh#tour)**

Ein Klick auf das Titelbild öffnet das Video auf der Website. Die Videos sind auf Englisch und Chinesisch verfügbar, mit Kapiteln zu Literatursuche, Bibliothek, Lesen, eigenen Publikationen und KI-Zusammenarbeit.

## Was Gewu unterstützt

- **Literatur verfolgen:** Journal, Subject und Author Monitor für Zeitschriften, Forschungsthemen und Autoren.
- **Material zusammenhalten:** Versionen, Ergänzungen, Anmerkungen und Notizen in Paper Files; die Default-Datei wählen Sie selbst.
- **Projekte organisieren:** Library und Spaces verweisen auf denselben Artikeldatensatz, auch wenn er mehreren Projekten zugeordnet ist.
- **Mit KI weiterlesen:** Freigegebene Originalquellen und frühere Analysen lesen und neue Analysen beim selben Artikel speichern.
- **Eigene Publikationen pflegen:** My Publications für Autorenrollen, Zitationsangaben und Exporte.

<details>
<summary>Einen echten Screenshot der App ansehen</summary>

![Echte macOS-Ansicht: Library-Ordner, veröffentlichte Fassung und Preprint eines Artikels sowie bibliografische Details](../../assets/user-guide/screenshots/library-paper-files.png)

</details>

Das [Produktvideo mit 5:19 Minuten Laufzeit](https://gewu-insight.com/product.html?lang=en#tour) zeigt diese Abläufe im Zusammenhang.

## Installation und Updates

| Plattform | Voraussetzungen | Download |
| --- | --- | --- |
| macOS | macOS 14 oder neuer; Apple silicon oder Intel | [DMG 1.1.0](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.1.0) |
| Windows | Windows 10 1607 (14393) oder neuer bzw. Windows 11; Intel/AMD x64 | [Setup 1.1.0](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.1.0) |

Laden Sie das Installationspaket unter **Assets** auf der Release-Seite herunter, nicht das **Source code**-ZIP. Auf dem Mac ziehen Sie die App aus dem DMG nach Applications; unter Windows führen Sie Setup aus und starten Gewu über das Startmenü.

Erstellen oder öffnen Sie eine **Gewu Database**, getrennt vom Programmordner. Unter Windows wählen Sie für vorhandene Bestände **Use existing Gewu Database**. Python und Abhängigkeiten sind enthalten; die gegebenenfalls nötige WebView2-Installation benötigt Internet. Das Mac-Paket ist nicht von Apple notarisiert, der Windows-Installer ist nicht signiert. Beachten Sie die [Installationshinweise](https://gewu-insight.com/download.html). LibreOffice und TeX sind optional und separat zu installieren.

Mac 1.0.x und Windows 1.0.0 müssen einmal manuell auf 1.1.0 aktualisiert werden; behalten Sie dabei die bestehende Datenbank. Danach nutzen Sie auf dem Mac **Gewu Insight → Check for Updates**, unter Windows **Help → Check for Updates**. Vor der Installation Daten sichern, den Gewu-Tab in Zotero schließen und Importe abschließen oder pausieren.

## Mit einem Artikel beginnen

Ziehen Sie ein vorhandenes PDF in die Library oder öffnen Sie den [Projektartikel](https://arxiv.org/abs/2610.14538) im Browser und wählen **Save to Gewu**. Falls das PDF dabei nicht verfügbar ist, laden Sie es von arXiv herunter und fügen es unter Paper Files demselben Datensatz hinzu.

1. Ordnen Sie den Artikel einem Forschungsordner zu, prüfen Sie **Paper Details** und lesen Sie das PDF.
2. Für KI richten Sie nach der [Verbindungsanleitung](../AI_ACCESS.md) **AI Access** ein und wählen Sammlung sowie benötigte Lese- und Analyseschreibrechte.
3. Ersetzen Sie den Platzhalter durch den tatsächlichen **Gewu Key** und bitten Sie den verbundenen Client:

   > Lies mit Gewus MCP-Werkzeugen den Artikel YOUR_GEWU_KEY und das freigegebene PDF. Fasse Forschungsfrage, Belege und Grenzen mit Seitenangaben zusammen. Speichere die Analyse mit save_analysis beim selben Artikel, einschließlich Quelldatei-ID und SHA-256. Überschreibe keine bestehenden Dateien.

4. Lassen Sie in einer späteren berechtigten Sitzung zunächst die Quelle und die gespeicherte Analyse lesen, bevor Sie offene Fragen weiterverfolgen. Die Notiz finden Sie in Paper Files.

Die Fortsetzung basiert auf gespeicherten Unterlagen. **KI-Chats werden nicht automatisch synchronisiert.** Literatursuche, Organisation und Lesen funktionieren auch ohne KI-Konto.

## Mit Zotero arbeiten

Installieren Sie das mitgelieferte Plugin in der eigenständigen App über **Plugin → Zotero Integration**. Der Zotero-Tab nutzt dieselbe Gewu-Installation und ausgewählte Datenbank, mit denselben Artikeln und Einstellungen.

**Save to Gewu** speichert in Gewu. **Save to Zotero** kopiert Metadaten und optional das vorhandene Default-PDF. **Loader → Import from Zotero** zeigt zuerst eine Vorschau und kopiert anschließend die Sammlungshierarchie einschließlich leerer Sammlungen nach Gewus Regeln für die lokale Dateiablage. Zotero-Daten und Originaldateien bleiben erhalten. Es handelt sich nicht um eine fortlaufende Synchronisierung in beide Richtungen. [Bebilderte Anleitung](https://gewu-insight.com/zotero.html).

## Daten, Plattformen und Lizenz

Datenbank, PDFs und Anhänge liegen lokal. Neue Literatur, Verlagsseiten und Online-KI benötigen eine Netzwerkverbindung. AI Access ist standardmäßig deaktiviert; der KI-Client kann freigegebene Inhalte an seinen Modellanbieter senden. Prüfen Sie Analysen anhand der Quellen. MCP-Rechte begrenzen nicht die unabhängigen Dateirechte eines Programms im Betriebssystem.

Beenden Sie App und Hintergrunddienst, bevor Sie die gesamte Datenbank, weitere verwaltete Ordner und extern verknüpfte Originale sichern. Eine Kopie des Programms allein ist keine Sicherung Ihrer Forschung. Gewu umgeht keine Bezahlschranken oder Zugriffskontrollen.

macOS ist die wichtigste Entwicklungs- und Testplattform. Windows 11 wurde begrenzt in einer virtuellen Maschine getestet; Windows-10-Korrekturen beruhen überwiegend auf externen Rückmeldungen. Die Abbildungen und die Evaluation im Fachartikel stammen von macOS.

Der Quellcode ist unter einer eigenen [Lizenz für akademische und nichtkommerzielle Forschung](../../LICENSE) verfügbar; dies ist keine Open-Source-Lizenz. Nutzung, Änderungen und Weitergabe sind nach deren Bedingungen erlaubt. Kommerzielle Nutzung erfordert eine gesonderte schriftliche Genehmigung. Für fremde Inhalte gelten deren eigene Bedingungen.

[Produktübersicht](https://gewu-insight.com/product.html) · [Handbücher beider Plattformen](https://gewu-insight.com/resources.html#resources) · [KI-Anbindung](https://gewu-insight.com/ai.html) · [Problem melden](https://github.com/LKong92/Gewu-Insight/issues)

Der chinesische Name „格物洞见“ steht für das Erforschen konkreter Phänomene und das Gewinnen von Einsichten durch physikalische Vorstellungen und Intuition. Forschungsfragen und wissenschaftliche Urteile bleiben Aufgabe der Forschenden.

Zitation: Kong, L. & Wu, Z. *A Stateful Research Information Infrastructure for Scientific Discovery.* arXiv:2610.14538 (2026). [Artikel](https://arxiv.org/abs/2610.14538) · [BibTeX und Reproduktionsmaterial](../../README.md#citation).

Copyright © 2026 Lingyuan Kong and Zhengran Wu.
