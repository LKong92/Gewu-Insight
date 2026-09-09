"""Disposable PDF-to-text worker; stdout contains only its bounded result."""
import json
import sys


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(sys.argv[1])
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('Encrypted PDF')
        start, count = int(sys.argv[2]), int(sys.argv[3])
        total = len(reader.pages)
        if start > total:
            print(json.dumps({'error': 'The requested page is beyond the end of the PDF.'}))
            return
        pages, budget = [], 64000
        for index in range(start - 1, min(total, start - 1 + count)):
            text = reader.pages[index].extract_text() or ''
            pages.append({'page': index + 1, 'text': text[:budget], 'truncated': len(text) > budget})
            budget -= min(len(text), budget)
            if budget <= 0:
                break
        next_page = pages[-1]['page'] + 1
        print(json.dumps({'pages': pages, 'total_pages': total,
                          'next_page': next_page if next_page <= total else None,
                          'ocr_needed': not any(p['text'].strip() for p in pages)}))
    except Exception:
        print(json.dumps({'error': 'Text could not be extracted. The PDF may be encrypted, damaged or require OCR.'}))


if __name__ == '__main__':
    main()
