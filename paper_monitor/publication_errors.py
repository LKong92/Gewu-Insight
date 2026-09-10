"""Short publication-work messages; technical exceptions stay in the server log."""
import logging


def publication_error_message(error, *, operation='Import'):
    detail = str(error).lower()
    kind = type(error).__name__.lower()
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status == 429 or any(word in detail for word in ('cooldown', 'unusual traffic', 'temporarily block', 'temporarily limiting access', 'captcha')):
        reason = 'The publication source is temporarily limiting access.'
    elif 'ssl' in kind or any(word in detail for word in ('sslerror', 'ssleoferror', 'secure connection')):
        reason = 'The secure connection to the publication source was interrupted.'
    elif 'timeout' in kind or any(word in detail for word in ('timed out', 'timeout', 'took too long')):
        reason = 'The publication source took too long to respond.'
    elif 'connection' in kind or any(word in detail for word in ('connectionpool', 'network', 'connection to the publication source')):
        reason = 'The connection to the publication source was interrupted.'
    elif any(word in detail for word in ('repeated a page', 'did not advance')):
        reason = 'The publication source repeated a page instead of returning more articles.'
    elif any(word in detail for word in ('could not be read', 'could not read')):
        reason = 'The publication list could not be read.'
    elif 'identity' in detail:
        return 'Some articles need identity review. Saved publications are unchanged; retry after reviewing their metadata.'
    else:
        reason = f'{operation} could not finish.'
    saved = ' Already imported publications are saved.' if operation == 'Import' else ''
    return f'{reason}{saved} Please try again later.'


def report_publication_error(error, *, operation='Import'):
    logging.getLogger(__name__).warning('%s failed', operation, exc_info=True)
    return publication_error_message(error, operation=operation)


def public_import_message(status, message):
    """Also protect snapshots of exceptions persisted by older app versions."""
    if status == 'error':
        return publication_error_message(message)
    if status == 'partial':
        return 'Some articles could not be added. Continue Import to retry them; already imported publications are saved.'
    return ''
