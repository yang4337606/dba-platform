"""
Markdown to HTML converter for Flask templates
"""
import markdown as md
from markupsafe import Markup


def markdown_to_html(text):
    """
    Convert Markdown text to HTML

    Args:
        text: Markdown formatted text

    Returns:
        HTML string wrapped in Markup for safe rendering
    """
    if not text:
        return Markup("")

    # Configure markdown extensions
    extensions = [
        'extra',          # Tables, fenced code blocks, etc.
        'codehilite',     # Code syntax highlighting
        'nl2br',          # Convert newlines to <br>
        'sane_lists',     # Better list handling
        'toc',            # Table of contents
    ]

    # Convert markdown to HTML
    html = md.markdown(
        text,
        extensions=extensions,
        extension_configs={
            'codehilite': {
                'css_class': 'highlight',
                'linenums': False,
            }
        }
    )

    return Markup(html)
