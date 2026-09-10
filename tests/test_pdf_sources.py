from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from pypdf import PdfWriter
from paper_monitor import download
from paper_monitor.pdf_sources import approved_pdf_source


class PdfSourceTests(TestCase):
    def test_reviewed_publisher_delivery_hosts_are_tenant_scoped(self):
        for host in ('acs.figshare.com', 'pdf.sciencedirectassets.com', 'oup.silverchair-cdn.com', 'watermark.silverchair.com'):
            self.assertTrue(approved_pdf_source('https://' + host + '/file.pdf'), host)
        for host in ('figshare.com', 'other.figshare.com', 'ndownloader.figshare.com', 'other.silverchair-cdn.com',
                     'oup.silverchair-cdn.com.invalid', 'sciencedirectassets.com.invalid', 's3.amazonaws.com'):
            self.assertFalse(approved_pdf_source('https://' + host + '/file.pdf'), host)

    def test_official_hosts_and_lookalikes(self):
        for url in ('https://www.nature.com/articles/a.pdf', 'https://arxiv.org/pdf/2601.01234',
                    'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/a.pdf', 'https://media.springernature.com/a.pdf'):
            self.assertTrue(approved_pdf_source(url), url)
        for url in ('https://nature.com.mirror.invalid/a.pdf', 'https://notnature.com/a.pdf',
                    'https://repository.example.edu/a.pdf', 'https://annas-archive.org/a.pdf',
                    'https://sci-hub.se/a.pdf', 'https://libgen.is/a.pdf', 'file:///a.pdf',
                    'https://nature.com@mirror.invalid/a.pdf', 'https://u:p@nature.com/a.pdf'):
            self.assertFalse(approved_pdf_source(url), url)

    def test_unverified_url_never_requests_or_overwrites_existing_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'paper.pdf'; target.write_bytes(b'original')
            with patch.object(download, 'request_with_retries') as request:
                self.assertFalse(download.try_download_pdf('https://mirror.invalid/a.pdf', target, []))
                request.assert_not_called()
            self.assertEqual(target.read_bytes(), b'original')

    def test_redirect_to_unverified_host_stops_before_following_or_reading(self):
        redirect = Mock(status_code=302, url='https://www.nature.com/a.pdf', headers={'Location':'https://mirror.invalid/a.pdf'})
        with patch.object(download, 'request_with_retries', return_value=redirect) as request:
            with self.assertRaisesRegex(ValueError, 'source is not verified'):
                download.document_request('https://www.nature.com/a.pdf')
            self.assertEqual(request.call_count, 1)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            redirect.iter_content.assert_not_called(); redirect.close.assert_called_once()

    def test_official_redirect_retains_pdf_validation_and_original(self):
        stream = BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=300, height=400); writer.write(stream)
        redirect = Mock(status_code=302, url='https://doi.org/10.1234/a', headers={'Location':'https://www.nature.com/a.pdf'})
        result = Mock(status_code=200, url='https://www.nature.com/a.pdf', headers={'content-type':'application/pdf'})
        result.iter_content.return_value = [stream.getvalue()]
        with TemporaryDirectory() as directory, patch.object(download, 'request_with_retries', side_effect=[redirect, result]) as request:
            target = Path(directory) / 'paper.pdf'
            self.assertTrue(download.try_download_pdf('https://doi.org/10.1234/a', target, []))
            self.assertEqual(target.read_bytes(), stream.getvalue())
            self.assertEqual(request.call_count, 2)
            self.assertTrue(all(not item.kwargs['allow_redirects'] for item in request.call_args_list))
