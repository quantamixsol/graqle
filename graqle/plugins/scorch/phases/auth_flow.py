"""Phase: Authenticated user journey audit — login/signup forms, protected routes, session indicators."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.scorch.auth_flow")

_AUTH_FLOW_JS = """
() => {
    const findings = {};

    // 1. Login form detection and quality
    findings.loginForm = null;
    const loginForm = document.querySelector(
        'form[action*="login"], form[action*="signin"], form[id*="login"], form[class*="login"]'
    ) || (document.querySelector('input[type="email"], input[name*="email"], input[name*="username"]') &&
          document.querySelector('input[type="password"]')
          ? document.querySelector('input[type="password"]')?.closest('form')
          : null);

    if (loginForm) {
        const emailField = loginForm.querySelector('input[type="email"], input[name*="email"], input[name*="username"]');
        const passwordField = loginForm.querySelector('input[type="password"]');
        const submitBtn = loginForm.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
        const hasPasswordToggle = !!loginForm.querySelector(
            '[class*="toggle"], [class*="show-pass"], [class*="eye"], [aria-label*="password"], [aria-label*="show"]'
        );
        const hasRememberMe = !!loginForm.querySelector('[name*="remember"], [id*="remember"]');
        const hasForgotPassword = !!loginForm.querySelector('a[href*="forgot"], a[href*="reset"], [class*="forgot"]');
        const hasErrorRegion = !!loginForm.querySelector('[role="alert"], [class*="error"], [aria-live]');
        const emailLabel = emailField ? (
            document.querySelector(`label[for="${emailField.id}"]`)?.textContent ||
            emailField.getAttribute('placeholder') ||
            emailField.getAttribute('aria-label')
        ) : null;

        findings.loginForm = {
            hasEmailField: !!emailField,
            hasPasswordField: !!passwordField,
            emailLabel: (emailLabel || '').trim().substring(0, 60),
            submitText: (submitBtn?.textContent || submitBtn?.value || '').trim().substring(0, 60),
            hasPasswordToggle,
            hasRememberMe,
            hasForgotPassword,
            hasErrorRegion,
            fieldCount: loginForm.querySelectorAll('input:not([type="hidden"])').length,
        };
    }

    // 2. Signup form detection and quality
    findings.signupForm = null;
    const signupForm = document.querySelector(
        'form[action*="signup"], form[action*="register"], form[id*="signup"], form[class*="signup"], form[class*="register"]'
    ) || (() => {
        // Heuristic: form with email + password + additional field (name, confirm password)
        const forms = document.querySelectorAll('form');
        for (const f of forms) {
            const hasEmail = !!f.querySelector('input[type="email"]');
            const passwords = f.querySelectorAll('input[type="password"]');
            const hasExtraField = f.querySelectorAll('input:not([type="hidden"])').length >= 3;
            if (hasEmail && passwords.length >= 1 && hasExtraField) return f;
        }
        return null;
    })();

    if (signupForm) {
        const passwordFields = signupForm.querySelectorAll('input[type="password"]');
        const hasConfirmPassword = passwordFields.length >= 2;
        const hasPasswordStrength = !!signupForm.querySelector(
            '[class*="strength"], [class*="password-hint"], [class*="requirements"], [aria-label*="strength"]'
        );
        const hasTermsCheckbox = !!signupForm.querySelector(
            'input[type="checkbox"][name*="terms"], input[type="checkbox"][id*="terms"], [class*="terms"]'
        );
        const submitBtn = signupForm.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
        const totalFields = signupForm.querySelectorAll('input:not([type="hidden"])').length;

        findings.signupForm = {
            totalFields,
            hasConfirmPassword,
            hasPasswordStrength,
            hasTermsCheckbox,
            submitText: (submitBtn?.textContent || submitBtn?.value || '').trim().substring(0, 60),
            hasErrorRegion: !!signupForm.querySelector('[role="alert"], [class*="error"], [aria-live]'),
        };
    }

    // 3. Session indicators (user is logged in)
    findings.sessionIndicators = {
        hasUserAvatar: !!document.querySelector(
            '[class*="avatar"], [class*="user-photo"], img[alt*="avatar"], img[alt*="profile"]'
        ),
        hasUserName: !!document.querySelector(
            '[class*="user-name"], [class*="username"], [class*="display-name"], [data-user]'
        ),
        hasLogoutButton: !!document.querySelector(
            'a[href*="logout"], a[href*="signout"], button[class*="logout"], [aria-label*="logout"], [aria-label*="sign out"]'
        ),
        hasAccountMenu: !!document.querySelector(
            '[class*="account-menu"], [class*="user-menu"], [class*="profile-menu"], [aria-label*="account"]'
        ),
        hasNotificationBell: !!document.querySelector(
            '[class*="notification"], [aria-label*="notification"], [class*="bell"]'
        ),
    };
    findings.sessionIndicators.isLoggedIn = (
        findings.sessionIndicators.hasLogoutButton ||
        (findings.sessionIndicators.hasUserAvatar && findings.sessionIndicators.hasAccountMenu)
    );

    // 4. Navigation post-auth — dashboard, settings, profile links
    findings.postAuthNavigation = {
        hasDashboardLink: !!document.querySelector('a[href*="dashboard"], a[href*="home"], nav a[href="/"]'),
        hasSettingsLink: !!document.querySelector('a[href*="settings"], a[href*="preferences"], [aria-label*="settings"]'),
        hasProfileLink: !!document.querySelector('a[href*="profile"], a[href*="account"], [aria-label*="profile"]'),
    };

    // 5. Protected page indicators (redirect patterns, auth guards)
    findings.protectedPageIndicators = {
        hasRedirectParam: /[?&](redirect|return|next|returnUrl|redirectUrl)=/i.test(window.location.search),
        hasAuthCookie: document.cookie.split(';').some(c => /token|session|auth|user/i.test(c.trim())),
        hasLocalStorageAuth: (() => {
            try {
                return Object.keys(localStorage).some(k => /token|auth|user|session/i.test(k));
            } catch (e) { return false; }
        })(),
        currentPath: window.location.pathname,
    };

    // 6. Password requirements visibility (if any password field exists)
    findings.passwordRequirements = null;
    const anyPasswordField = document.querySelector('input[type="password"]');
    if (anyPasswordField) {
        findings.passwordRequirements = {
            hasVisibleRequirements: !!document.querySelector(
                '[class*="password-req"], [class*="requirements"], [class*="strength-indicator"], [class*="hint"]'
            ),
            hasMinLengthHint: /\\d+\\s*(characters|chars|minimum)/i.test(document.body.textContent || ''),
        };
    }

    // Summary
    findings.summary = {
        hasLoginForm: !!findings.loginForm,
        hasSignupForm: !!findings.signupForm,
        isLoggedIn: findings.sessionIndicators.isLoggedIn,
        hasPostAuthNav: Object.values(findings.postAuthNavigation).some(Boolean),
        hasSessionStorage: findings.protectedPageIndicators.hasAuthCookie ||
                           findings.protectedPageIndicators.hasLocalStorageAuth,
    };

    return findings;
}
"""

_AUTH_REDIRECT_JS = """
() => {
    return {
        currentUrl: window.location.href,
        currentPath: window.location.pathname,
        hasLoginForm: !!document.querySelector('input[type="password"]'),
        redirectedToLogin: /login|signin|auth/i.test(window.location.pathname),
        hasRedirectParam: /[?&](redirect|return|next|returnUrl|redirectUrl)=/i.test(window.location.search),
    };
}
"""


async def audit_auth_flow(config: Any) -> list[dict[str, Any]]:
    """Run authenticated user journey audit across all pages x viewports.

    First passes WITHOUT auth state (checks redirect behavior and login/signup UI).
    Second pass WITH auth_state (if configured) checks session indicators and
    post-auth navigation.

    Returns list of:
        {"page": str, "viewport": str, "url": str, "auth_state": str, "findings": {...}}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("SCORCH requires playwright. Install with: pip install graqle[scorch]")

    results: list[dict[str, Any]] = []

    # Known auth page paths to always include in testing
    auth_pages = ["/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up"]
    all_pages = list(config.pages)
    for auth_page in auth_pages:
        if auth_page not in all_pages:
            all_pages.append(auth_page)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # --- Pass 1: Unauthenticated ---
        for vp in config.viewports:
            context = await browser.new_context(
                viewport={"width": vp.width, "height": vp.height},
                device_scale_factor=vp.device_scale_factor,
                # No auth_state — intentionally unauthenticated
            )
            page = await context.new_page()

            for page_path in all_pages:
                url = f"{config.base_url.rstrip('/')}{page_path}"
                logger.info("Auth flow audit (unauthenticated): %s @ %s", url, vp.name)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(config.wait_after_load)

                    findings = await page.evaluate(_AUTH_FLOW_JS)
                    redirect_info = await page.evaluate(_AUTH_REDIRECT_JS)
                    findings["redirectInfo"] = redirect_info

                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "auth_state": "unauthenticated",
                        "findings": findings,
                    })
                except Exception as exc:
                    logger.error(
                        "Auth flow audit (unauth) failed for %s @ %s: %s", url, vp.name, exc
                    )
                    results.append({
                        "page": page_path,
                        "viewport": vp.name,
                        "url": url,
                        "auth_state": "unauthenticated",
                        "error": str(exc),
                    })

            await context.close()

        # --- Pass 2: Authenticated (only if auth_state is configured) ---
        if config.auth_state:
            logger.info("Auth flow audit: starting authenticated pass with state=%s", config.auth_state)
            for vp in config.viewports:
                context = await browser.new_context(
                    viewport={"width": vp.width, "height": vp.height},
                    device_scale_factor=vp.device_scale_factor,
                    storage_state=config.auth_state,
                )
                page = await context.new_page()

                for page_path in config.pages:
                    url = f"{config.base_url.rstrip('/')}{page_path}"
                    logger.info("Auth flow audit (authenticated): %s @ %s", url, vp.name)

                    try:
                        await page.goto(url, wait_until="networkidle", timeout=30000)
                        await page.wait_for_timeout(config.wait_after_load)

                        findings = await page.evaluate(_AUTH_FLOW_JS)
                        redirect_info = await page.evaluate(_AUTH_REDIRECT_JS)
                        findings["redirectInfo"] = redirect_info

                        results.append({
                            "page": page_path,
                            "viewport": vp.name,
                            "url": url,
                            "auth_state": "authenticated",
                            "findings": findings,
                        })
                    except Exception as exc:
                        logger.error(
                            "Auth flow audit (auth) failed for %s @ %s: %s", url, vp.name, exc
                        )
                        results.append({
                            "page": page_path,
                            "viewport": vp.name,
                            "url": url,
                            "auth_state": "authenticated",
                            "error": str(exc),
                        })

                await context.close()
        else:
            logger.info(
                "Auth flow audit: skipping authenticated pass — no auth_state in config. "
                "Set config.auth_state to a Playwright storage state path to enable."
            )

        await browser.close()

    logger.info("Auth flow audit complete: %d test sets", len(results))
    return results
