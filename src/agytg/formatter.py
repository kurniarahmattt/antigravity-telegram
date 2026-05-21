"""Convert agy's CommonMark-ish output into Telegram-safe HTML.

Telegram's HTML mode supports a small subset: <b>, <i>, <u>, <s>, <code>, <pre>,
<a href>, <blockquote>, <tg-spoiler>. We convert what agy commonly emits:
- `**bold**`, `__bold__`           → <b>...</b>
- `*italic*`, `_italic_`           → <i>...</i>
- `` `inline code` ``              → <code>...</code>
- ```` ```lang\\n...code...\\n``` ```` → <pre><code class="language-X">...</code></pre>
- `[text](url)`                    → <a href="url">text</a>
- `# Heading`...`###### Heading`   → <b>Heading</b>
- `~~strike~~`                     → <s>...</s>

Lists / tables / horizontal rules are passed through with markers stripped to
their plain-text content. Order matters: we extract code first so its contents
are not mangled by other rules.
"""

from __future__ import annotations

import html
import re

# ----- placeholders for code segments -----
_PLACEHOLDER = "\x00AGYTG_PH_{kind}_{idx}\x00"


def _escape_html(s: str) -> str:
    return html.escape(s, quote=False)


def markdown_to_telegram_html(text: str) -> str:
    if not text:
        return ""

    blocks: list[str] = []
    inlines: list[str] = []

    def stash_block(match: re.Match) -> str:
        idx = len(blocks)
        lang = match.group(1) or ""
        body = match.group(2)
        blocks.append((lang, body))
        return _PLACEHOLDER.format(kind="BLK", idx=idx)

    def stash_inline(match: re.Match) -> str:
        idx = len(inlines)
        inlines.append(match.group(1))
        return _PLACEHOLDER.format(kind="INL", idx=idx)

    # 1. Stash fenced code blocks first.
    text = re.sub(
        r"```([a-zA-Z0-9_+-]*)\n(.*?)```",
        stash_block,
        text,
        flags=re.DOTALL,
    )
    # 2. Stash inline code.
    text = re.sub(r"`([^`\n]+)`", stash_inline, text)

    # 3. Escape the remaining HTML metacharacters.
    text = _escape_html(text)

    # 4. Headers: leading 1–6 #s → bold + newline.
    text = re.sub(
        r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$",
        lambda m: f"<b>{m.group(2).strip()}</b>",
        text,
        flags=re.MULTILINE,
    )

    # 5. Bold: **...** or __...__ (non-greedy, no newline span).
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)

    # 6. Strikethrough.
    text = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", text)

    # 7. Italic: *...* or _..._ — avoid matching list bullets or word_word.
    # Require the * or _ to be at a word boundary / start of text.
    text = re.sub(
        r"(?<![\w*])\*([^*\n]+?)\*(?!\w)",
        r"<i>\1</i>",
        text,
    )
    text = re.sub(
        r"(?<![\w_])_([^_\n]+?)_(?!\w)",
        r"<i>\1</i>",
        text,
    )

    # 8. Links: [text](url)
    def _link(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        # url is already HTML-escaped at step 3; un-escape & re-escape for href.
        url_attr = html.escape(html.unescape(url), quote=True)
        return f'<a href="{url_attr}">{label}</a>'

    text = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", _link, text)

    # 9. List bullets: strip the marker, keep the content. Telegram has no list,
    # so we render them as "• item" lines for readability.
    text = re.sub(r"^[ \t]*[-*+][ \t]+", "• ", text, flags=re.MULTILINE)

    # 10. Horizontal rules → blank line.
    text = re.sub(r"^[ \t]*([-*_])\1\1[\1 \t]*$", "", text, flags=re.MULTILINE)

    # 11. Restore inline code placeholders.
    for i, raw in enumerate(inlines):
        token = _PLACEHOLDER.format(kind="INL", idx=i)
        text = text.replace(token, f"<code>{_escape_html(raw)}</code>")

    # 12. Restore fenced blocks.
    for i, (lang, body) in enumerate(blocks):
        token = _PLACEHOLDER.format(kind="BLK", idx=i)
        body_html = _escape_html(body.rstrip("\n"))
        if lang:
            lang_attr = html.escape(lang, quote=True)
            replacement = f'<pre><code class="language-{lang_attr}">{body_html}</code></pre>'
        else:
            replacement = f"<pre>{body_html}</pre>"
        text = text.replace(token, replacement)

    # Collapse 3+ blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text
