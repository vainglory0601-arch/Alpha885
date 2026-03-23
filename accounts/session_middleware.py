"""
Multi-portal session middleware.

Assigns a separate browser cookie to each portal so you can be logged in
as a regular user AND as staff/admin simultaneously in the same Chrome tab.

  /admin/*  and  /staff/*  →  staffsid   (staff + admin share one session)
  everything else           →  sessionid  (user portal — UNCHANGED)

Existing clients are not affected: they use "sessionid" exactly as before.
"""

import time

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import SuspiciousOperation
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date

# Staff portal and Django admin share one session so login at /admin/login/
# naturally carries over to /staff/* views.
STAFF_COOKIE_NAME = "staffsid"


def _cookie_name_for(path: str) -> str:
    """Return the correct session cookie name for this request path."""
    if path.startswith("/admin/") or path.startswith("/staff/"):
        return STAFF_COOKIE_NAME
    return settings.SESSION_COOKIE_NAME  # "sessionid" — user portal, unchanged


class MultiPortalSessionMiddleware(SessionMiddleware):
    """
    Drop-in replacement for Django's SessionMiddleware.
    Only difference: portal-specific cookie names.
    """

    def process_request(self, request):
        cookie_name = _cookie_name_for(request.path_info)
        session_key = request.COOKIES.get(cookie_name)
        request.session = self.SessionStore(session_key)
        # Store so process_response uses the same name without re-computing path
        request._portal_cookie_name = cookie_name

    def process_response(self, request, response):
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        cookie_name = getattr(
            request, "_portal_cookie_name", settings.SESSION_COOKIE_NAME
        )

        if accessed:
            patch_vary_headers(response, ("Cookie",))

        # If session is now empty and the cookie was present, delete it
        if cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                cookie_name,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            patch_vary_headers(response, ("Cookie",))
            return response

        # Save + set cookie when session was modified (or save-every-request)
        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            if response.status_code == 500:
                return response

            if request.session.get_expire_at_browser_close():
                max_age = None
                expires = None
            else:
                max_age = request.session.get_expiry_age()
                expires = http_date(time.time() + max_age)

            try:
                request.session.save()
            except UpdateError:
                raise SuspiciousOperation(
                    "The request's session was deleted before the request "
                    "completed. The user may have logged out in a concurrent "
                    "request, for example."
                )

            response.set_cookie(
                cookie_name,
                request.session.session_key,
                max_age=max_age,
                expires=expires,
                domain=settings.SESSION_COOKIE_DOMAIN,
                path=settings.SESSION_COOKIE_PATH,
                secure=settings.SESSION_COOKIE_SECURE or request.is_secure(),
                httponly=settings.SESSION_COOKIE_HTTPONLY,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )

        return response
