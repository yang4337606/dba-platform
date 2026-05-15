from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    # Register Markdown filter
    from app.markdown_filter import markdown_to_html
    app.jinja_env.filters['markdown'] = markdown_to_html

    from app.routes import bp as main_bp
    from app.routes_async import bp_async

    app.register_blueprint(main_bp)
    app.register_blueprint(bp_async)

    # Seed built-in knowledge on first run
    _seed_knowledge()

    return app


def _seed_knowledge():
    """Seed expert patterns into knowledge base on first run."""
    try:
        from app.knowledge import KnowledgeBase
        from app.seed_patterns import BUILTIN_PATTERNS

        kb = KnowledgeBase()
        existing = kb.get_all_patterns()
        builtin_count = sum(1 for p in existing if p.get("source") == "builtin")

        if builtin_count == 0:
            added = kb.seed_builtin_patterns(BUILTIN_PATTERNS)
            if added:
                import logging
                logging.getLogger(__name__).info("Seeded %d built-in expert patterns", added)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Knowledge seed skipped: %s", e)
