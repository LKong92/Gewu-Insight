import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import windows_word_pdf


@unittest.skipUnless(sys.platform == 'win32', 'Windows Word conversion boundary')
class WindowsWordPdfTests(unittest.TestCase):
    def test_existing_output_is_never_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source.docx', Path(directory)/'existing.pdf'
            source.write_bytes(b'fixture'); target.write_bytes(b'existing research')
            with patch.object(subprocess, 'run') as run:
                with self.assertRaises(FileExistsError): windows_word_pdf.convert(source,target)
                run.assert_not_called()
            self.assertEqual(target.read_bytes(), b'existing research')

    def test_timed_out_child_cleans_only_its_partial_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source.docx', Path(directory)/'generated.pdf'
            source.write_bytes(b'original')
            def timeout(*args, **kwargs):
                self.assertTrue(kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
                target.write_bytes(b'partial')
                raise subprocess.TimeoutExpired(args[0],70)
            with patch.object(subprocess,'run',side_effect=timeout):
                with self.assertRaisesRegex(OSError, 'timed out'): windows_word_pdf.convert(source,target)
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b'original')

    def test_invalid_conversion_is_rejected_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source.doc', Path(directory)/'generated.pdf'
            source.write_bytes(b'original')
            def convert(*args, **kwargs):
                target.write_bytes(b'not a PDF')
                return subprocess.CompletedProcess(args[0],0,'','')
            with patch.object(subprocess,'run',side_effect=convert):
                with self.assertRaises(OSError): windows_word_pdf.convert(source,target)
            self.assertFalse(target.exists())


if __name__ == '__main__': unittest.main()
