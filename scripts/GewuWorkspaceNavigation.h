#import "GewuBrowserNavigation.h"

// Only the trusted local main document may request a Browser tab. A popup
// created here must NOT inherit that document's privileged WK configuration.
static inline BOOL GewuWorkspaceSameOrigin(NSURL *url, NSURL *workspace) {
    return url && workspace && [url.scheme.lowercaseString isEqualToString:workspace.scheme.lowercaseString]
        && [url.host.lowercaseString isEqualToString:workspace.host.lowercaseString]
        && (url.port.integerValue ?: 80) == (workspace.port.integerValue ?: 80)
        && !url.user.length && !url.password.length;
}

static inline BOOL GewuWorkspaceWebsiteRequest(NSURLRequest *request, NSURL *source, BOOL mainFrame, NSURL *workspace) {
    return mainFrame && GewuWorkspaceSameOrigin(source, workspace)
        && GewuBrowserPublicURL(request.URL)
        && !GewuWorkspaceSameOrigin(request.URL, workspace)
        && GewuBrowserCanRetainHomeForRequest(request);
}
