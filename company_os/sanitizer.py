"""Prompt injection detection, delimiter isolation, and secret redaction."""

import re
import secrets

_INJECTION_PATTERNS = (
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:system|developer)\s+(?:prompts?|instructions?)\b"),
    re.compile(r"(?i)\breveal\s+(?:the\s+)?(?:system\s+prompt|secret|api[_-]?key)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:in\s+)?(?:developer|jailbreak|unrestricted)\s+mode\b"),
    re.compile(r"(?i)\bsystem\s+override\s*:"),
    re.compile(r"(?i)\[(?:system|admin|override)\s+prompt\]"),
)


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """Inspect text for known prompt injection and jailbreak signatures.

    Args:
        text: Untrusted string input (e.g. PR diff, commit log, issue body).

    Returns:
        A tuple ``(detected, matched_pattern)`` where detected is True if an
        injection signature was found.
    """
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return True, match.group(0)
    return False, None


def isolate_untrusted_input(content: str, label: str = "ARTIFACT") -> tuple[str, str, bool]:
    """Wrap untrusted external data within a cryptographically isolated boundary tag.

    Args:
        content: Untrusted text artifact.
        label: Semantic label for the artifact (e.g. 'CI_LOG', 'DIFF', 'DOC').

    Returns:
        A tuple of:
        - The sanitized, isolated string wrapped in ``<LABEL_{nonce}>...</LABEL_{nonce}>``.
        - The unique boundary nonce.
        - A boolean indicating whether prompt injection was detected.
    """
    nonce = secrets.token_hex(8)
    detected, pattern = detect_prompt_injection(content)
    warning_attr = f' security_warning="SUSPECTED_INJECTION: {pattern}"' if detected else ""
    wrapped = f"<{label}_{nonce}{warning_attr}>\n{content}\n</{label}_{nonce}>\n"
    return wrapped, nonce, detected
