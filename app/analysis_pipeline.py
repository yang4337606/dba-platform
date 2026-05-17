"""
Shared analysis pipeline used by both sync and async routes.
Extracts common logic to avoid code duplication.
"""
import logging
from typing import Any

from app.core.registry import get_analyzer
from app.core.renderer import render_markdown
from app.knowledge import KnowledgeBase
from app.models import db
from app.rag import get_retriever
from app.advisor import advisor

logger = logging.getLogger(__name__)

# Shared KnowledgeBase instance
kb = KnowledgeBase()


def run_analysis(file_content: bytes, filename: str, analyzer_type: str,
                 *, enable_deep_analysis: bool = False) -> dict[str, Any]:
    """Run the full analysis pipeline.

    Returns a dict with keys: success, result, markdown, llm_result,
    similar_cases, smart_recommendations, learning_feedback, kb_stats,
    record_id, error.
    """
    # 1. Parse & analyze
    analyzer = get_analyzer(analyzer_type)
    result = analyzer.analyze(file_content)
    markdown = render_markdown(result)

    # 2. Rule engine (optional, for learning)
    rule_results = _run_rule_engine(result)

    # 3. LLM enhancement
    llm_result = None
    deep_result = None
    learning_feedback = None
    llm_config = kb.load_config()
    if llm_config.get("api_key"):
        llm_result, deep_result, learning_feedback = _run_llm_analysis(
            llm_config, result, rule_results, analyzer,
            enable_deep=enable_deep_analysis,
        )

    # 4. Save to history
    record_id = _save_history(filename, analyzer_type, result, llm_result, markdown)

    # 5. Similar cases via RAG
    similar_cases = _find_similar_cases(result, record_id, filename, analyzer_type)

    # 6. Smart recommendations
    smart_recommendations = _generate_recommendations(result)

    # 7. Knowledge stats
    kb_stats = kb.get_stats()

    return {
        "success": True,
        "result": result,
        "markdown": markdown,
        "llm_result": llm_result,
        "deep_result": deep_result,
        "similar_cases": similar_cases,
        "smart_recommendations": smart_recommendations,
        "learning_feedback": learning_feedback,
        "kb_stats": kb_stats,
        "record_id": record_id,
    }


def _run_rule_engine(result):
    """Run the rule engine for learning extraction."""
    import os
    try:
        rules_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "analyzers", "oracle_awr", "rules.yaml",
        )
        import yaml
        with open(rules_path, encoding="utf-8") as f:
            rules = yaml.safe_load(f)
        from app.core.rule_engine import evaluate_rules_grouped
        workload_type = (result.raw_metrics or {}).get("workload_type", "Mixed")
        return evaluate_rules_grouped(result.raw_metrics or {}, rules, workload_type)
    except Exception:
        return None


def _run_llm_analysis(llm_config, result, rule_results, analyzer, *, enable_deep=False):
    """Run LLM analysis and pattern learning."""
    llm_result = None
    deep_result = None
    learning_feedback = None

    try:
        from app.llm import LLMClient
        client = LLMClient(**llm_config)
        active_patterns = kb.get_active_patterns()
        llm_result = client.analyze(result, result.raw_metrics or {}, active_patterns)

        if llm_result and not llm_result.get("error"):
            kb.save_case(result, llm_result)
            learned_pattern_ids = kb.learn_patterns(llm_result.get("learned_patterns", []))

            # Extract learnable patterns from rule engine
            try:
                context = analyzer.build_analysis_context(result.raw_metrics or {})
                learnable = analyzer.extract_learnable_patterns(
                    result.raw_metrics or {}, rule_results, context
                )
                if learnable:
                    engine_learned_ids = kb.learn_patterns(learnable)
                    learned_pattern_ids.extend(pid for pid in engine_learned_ids if pid)
            except Exception as e:
                logger.warning("Learnable pattern extraction failed: %s", e)

            learning_feedback = {
                "new_patterns_count": len([pid for pid in learned_pattern_ids if pid]),
                "new_patterns": llm_result.get("learned_patterns", []),
                "total_patterns": len(kb.get_all_patterns()),
                "active_patterns": len(kb.get_active_patterns()),
            }

        # Deep analysis
        if enable_deep:
            try:
                deep_result = client.deep_analyze(result, result.raw_metrics or {}, active_patterns)
                if deep_result and not deep_result.get("error"):
                    result.llm_deep_analysis = deep_result
                    deep_patterns = deep_result.get("learned_patterns", [])
                    if deep_patterns:
                        deep_learned = kb.learn_patterns(deep_patterns)
                        if learning_feedback:
                            learning_feedback["new_patterns_count"] += len(
                                [pid for pid in deep_learned if pid]
                            )
            except Exception as deep_exc:
                logger.warning("LLM deep analysis failed: %s", deep_exc)

    except Exception as exc:
        logger.warning("LLM enhancement failed: %s", exc)

    return llm_result, deep_result, learning_feedback


def _save_history(filename, analyzer_type, result, llm_result, markdown):
    """Save analysis to history database."""
    try:
        return db.save_analysis(
            filename=filename,
            analyzer_type=analyzer_type,
            result=result.to_dict() if hasattr(result, 'to_dict') else {},
            llm_result=llm_result if llm_result and not llm_result.get("error") else None,
            markdown=markdown,
        )
    except Exception as e:
        logger.warning("Failed to save history: %s", e)
        return None


def _find_similar_cases(result, record_id, filename, analyzer_type):
    """Find similar historical cases via RAG retrieval."""
    similar_cases = []
    try:
        result_dict = result.to_dict() if hasattr(result, 'to_dict') else {}
        main_problem = result_dict.get("main_bottleneck", "")
        diagnosis_summary = result_dict.get("summary", "")
        query_text = f"{main_problem} {diagnosis_summary}"

        if query_text.strip():
            retriever = get_retriever(db)
            rag_results = retriever.search(query_text, limit=3, min_similarity=0.1)

            if record_id:
                retriever.add_record({
                    'id': record_id,
                    'main_problem': main_problem,
                    'diagnosis_summary': diagnosis_summary,
                    'load_type': result_dict.get("diagnosis", {}).get("load_type", ""),
                    'filename': filename,
                    'analyzer_type': analyzer_type,
                })

            for item in rag_results:
                record = item['record']
                record['similarity'] = item['similarity']
                similar_cases.append(record)
    except Exception as e:
        logger.warning("Failed to get similar cases: %s", e)
    return similar_cases


def _generate_recommendations(result):
    """Generate smart recommendations."""
    try:
        return advisor.generate_recommendations(result, db_identifier=None)
    except Exception as e:
        logger.warning("Failed to generate smart recommendations: %s", e)
        return []
