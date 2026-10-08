from __future__ import annotations

import unittest

from paper_monitor.ui_server import INDEX_HTML


class DialogVisualContractTests(unittest.TestCase):
    def test_recycle_delete_retains_macos_confirmation_and_uses_windows_app_dialog(self) -> None:
        dialog = INDEX_HTML.split("function confirmRecycleDeletion", 1)[1].split(
            "function libraryFolderContentCounts", 1
        )[0]

        self.assertIn('window.confirm(lines.join("\\n"))', dialog)
        self.assertIn('return window.gewuConfirmDeletion({', dialog)
        self.assertIn("Managed local cop", dialog)
        self.assertIn("macOS Trash", dialog)
        self.assertIn("Original imported source files outside Gewu Insight will not be touched.", dialog)
        self.assertNotIn("recycle-alert-content", dialog)
        self.assertNotIn("recycle-delete-confirm", INDEX_HTML)

    def test_preferences_use_macos_grouped_lists_without_brand_artwork(self) -> None:
        settings = INDEX_HTML.split('id="citationSettingsBackdrop"', 1)[1].split(
            'id="libraryLoaderBackdrop"', 1
        )[0]
        cards = INDEX_HTML.split(".settings-modal.preferences-modal {", 1)[1].split(
            ".citation-settings-status", 1
        )[0]

        self.assertGreaterEqual(settings.count("preferences-modal"), 5)
        self.assertIn(".preferences-modal .citation-source-setting {", cards)
        self.assertIn("background: #ececee;", cards)
        self.assertIn("border-bottom: 1px solid rgba(60, 60, 67, 0.13);", cards)
        self.assertNotIn("app-icon", settings)

    def test_dialogs_start_on_the_surface_and_use_a_macos_close_control(self) -> None:
        self.assertIn("function focusDialogSurface(backdrop)", INDEX_HTML)
        self.assertIn("surface.focus({preventScroll: true})", INDEX_HTML)
        self.assertIn(".settings-modal-close::after,", INDEX_HTML)
        self.assertIn("background: #ff5f57;", INDEX_HTML)
        self.assertNotIn('$("openalexKeyInput")?.focus', INDEX_HTML)
        self.assertNotIn('$("pdfRenameJournalInput")?.focus', INDEX_HTML)

    def test_loader_uses_a_grouped_workflow_surface_without_brand_icon(self) -> None:
        loader_css = INDEX_HTML.split(".loader-panel {", 1)[1].split(
            ".loader-panel:has(.loader-result)", 1
        )[0]
        loader_markup = INDEX_HTML.split("function renderLibraryLoader", 1)[1].split(
            "function openLibraryLoader", 1
        )[0]

        self.assertIn("border-radius: 12px;", loader_css)
        self.assertIn(".loader-form {", loader_css)
        self.assertIn("background: rgba(255, 255, 255, 0.82);", loader_css)
        self.assertIn('class="loader-panel"', loader_markup)
        self.assertIn('class="loader-form"', loader_markup)
        self.assertNotIn("app-icon", loader_markup)

    def test_unsupported_internal_preview_uses_file_identity_not_branding(self) -> None:
        preview = INDEX_HTML.split("function renderLibraryFilePreviewCard", 1)[1].split(
            "async function renderLibraryQuickLookFilePreview", 1
        )[0]

        self.assertIn('class="library-file-preview-card-icon"', preview)
        self.assertIn('class="library-file-preview-card-title"', preview)
        self.assertIn('class="library-file-preview-card-meta"', preview)
        self.assertIn('class="library-file-preview-card-path"', preview)
        self.assertIn('class="library-file-preview-card-actions"', preview)
        self.assertIn("libraryFileExtension(paper)", preview)
        self.assertNotIn("app-icon", preview)


if __name__ == "__main__":
    unittest.main()
