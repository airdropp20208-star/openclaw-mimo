"""
Hermes AI Server
================
Flask HTTP server on :8081 providing AI capabilities for the Go+Python hybrid system.

Endpoints:
    POST /reason   - LLM reasoning (chat completion / task analysis)
    POST /execute  - Task execution with tools
    POST /plan     - Task decomposition
    POST /learn    - Extract skills from task result
    GET  /health   - Health check

Usage:
    python server.py                    # Run with Flask dev server
    gunicorn server:app -b 0.0.0.0:8081  # Production

Environment Variables:
    LLM_API_KEYS     - Comma-separated API keys (required)
    LLM_API_BASE     - API base URL (default: https://api.xiaomimimo.com/v1)
    LLM_MODEL        - Model name (default: mimo-v2.5)
    HERMES_WORKDIR   - Working directory for file ops (default: cwd)
    HERMES_SKILLS_DIR - Skills storage directory (default: ~/.hermes/skills)
    PORT             - Server port (default: 8081)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from typing import Any

from flask import Flask, Response, jsonify, request

# ---------------------------------------------------------------------------
# RAG imports (optional, gracefully handled)
# ---------------------------------------------------------------------------
_rag_available = False
_rag_pipeline = None
_skills_indexer = None
_memory_indexer = None

try:
    from rag import get_rag_pipeline
    from rag.skills_indexer import SkillsIndexer as _SkillsIndexer
    from rag.memory_indexer import MemoryIndexer as _MemoryIndexer
    _rag_available = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai_server")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global singletons (lazy-initialized)
# ---------------------------------------------------------------------------
_llm_client = None
_skills_learner = None


def _get_rag():
    global _rag_pipeline, _skills_indexer, _memory_indexer, _rag_available
    if not _rag_available:
        return None
    if _rag_pipeline is None:
        try:
            _rag_pipeline = get_rag_pipeline()
            _skills_indexer = _SkillsIndexer(pipeline=_rag_pipeline)
            _memory_indexer = _MemoryIndexer(pipeline=_rag_pipeline)
            logger.info("RAG pipeline initialized")
        except Exception as exc:
            logger.warning("RAG pipeline init failed: %s", exc)
            _rag_available = False
            return None
    return _rag_pipeline


def _get_llm():
    global _llm_client
    if _llm_client is None:
        from llm.client import get_llm_client
        _llm_client = get_llm_client()
    return _llm_client


def _get_skills_learner():
    global _skills_learner
    if _skills_learner is None:
        from ai.skills_learner import SkillsLearner
        _skills_learner = SkillsLearner()
    return _skills_learner


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def _parse_json_body() -> tuple[dict[str, Any], str | None]:
    """Parse JSON body from request, return (data, error_msg)."""
    if not request.is_json:
        return {}, "Content-Type must be application/json"
    data = request.get_json(silent=True)
    if data is None:
        return {}, "Invalid JSON body"
    return data, None


def _ok(data: Any = None, message: str = "ok") -> Response:
    """Build a success JSON response."""
    payload: dict[str, Any] = {"status": "ok", "message": message}
    if data is not None:
        payload["data"] = data
    return jsonify(payload)


def _err(message: str, status: int = 400, error: str = "bad_request") -> Response:
    """Build an error JSON response."""
    return jsonify({
        "status": "error",
        "error": error,
        "message": message,
    }), status


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health() -> Response:
    """Health check endpoint."""
    try:
        llm = _get_llm()
        llm_healthy = len(llm.api_keys) > 0
    except Exception:
        llm_healthy = False

    try:
        learner = _get_skills_learner()
        skill_count = len(learner.list_skills())
    except Exception:
        skill_count = 0

    return jsonify({
        "status": "ok",
        "service": "hermes-ai-server",
        "version": "1.1.0",
        "llm_available": llm_healthy,
        "skills_count": skill_count,
        "rag_available": _rag_available and _rag_pipeline is not None,
        "uptime": time.time(),
    })


# ---------------------------------------------------------------------------
# POST /rag/index — Index a document
# ---------------------------------------------------------------------------
@app.route("/rag/index", methods=["POST"])
def rag_index() -> Response:
    """Index a document into the RAG vector store.

    Request body:
        {
            "id": "document_id",
            "text": "document content",
            "metadata": { ... }   // optional
        }
    """
    rag = _get_rag()
    if rag is None:
        return _err("RAG not available", 503, "rag_unavailable")

    data, err = _parse_json_body()
    if err:
        return _err(err)

    doc_id = data.get("id", "")
    text = data.get("text", "")
    if not doc_id or not text:
        return _err("'id' and 'text' are required")

    try:
        doc_id = rag.index_document(text=text, metadata=data.get("metadata"))
        return _ok({"doc_id": doc_id}, "Document indexed")
    except Exception as exc:
        logger.exception("RAG index failed")
        return _err(f"Index failed: {exc}", 500, "index_error")


# ---------------------------------------------------------------------------
# POST /rag/search — Search similar documents
# ---------------------------------------------------------------------------
@app.route("/rag/search", methods=["POST"])
def rag_search() -> Response:
    """Search the RAG index for similar documents.

    Request body:
        {
            "query": "search query",
            "top_k": 5,             // optional
            "filter": { ... }       // optional metadata filter
        }
    """
    rag = _get_rag()
    if rag is None:
        return _err("RAG not available", 503, "rag_unavailable")

    data, err = _parse_json_body()
    if err:
        return _err(err)

    query = data.get("query", "")
    if not query:
        return _err("'query' is required")

    try:
        results = rag.retrieve(query, top_k=data.get("top_k", 5))
        result_dicts = [r.to_dict() for r in results]
        return _ok({"results": result_dicts, "count": len(result_dicts)})
    except Exception as exc:
        logger.exception("RAG search failed")
        return _err(f"Search failed: {exc}", 500, "search_error")


# ---------------------------------------------------------------------------
# POST /rag/rebuild — Rebuild index from files
# ---------------------------------------------------------------------------
@app.route("/rag/rebuild", methods=["POST"])
def rag_rebuild() -> Response:
    """Rebuild the RAG index from a directory of files.

    Request body:
        {
            "directory": "/path/to/files",  // optional, defaults to workdir
            "extensions": [".txt", ".md"]   // optional, file extensions to index
        }
    """
    rag = _get_rag()
    if rag is None:
        return _err("RAG not available", 503, "rag_unavailable")

    data, err = _parse_json_body()
    if err:
        return _err(err)

    try:
        directory = data.get("directory", os.environ.get("HERMES_WORKDIR", "."))
        extensions = data.get("extensions", [".txt", ".md", ".py", ".json", ".yaml", ".yml"])

        rag.clear()
        indexed = 0
        errors = 0

        for root, dirs, files in os.walk(directory):
            # Skip hidden dirs and common excludes
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv"}]

            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in extensions and fpath.stat().st_size < 1_000_000:
                    try:
                        text = fpath.read_text(encoding="utf-8", errors="ignore")
                        if text.strip():
                            doc_id = str(fpath.relative_to(directory)).replace(os.sep, "/")
                            rag.index_document(
                                text=text,
                                metadata={"source": str(fpath), "filename": doc_id},
                            )
                            indexed += 1
                    except Exception:
                        errors += 1

        rag.persist()
        stats = rag.stats()
        return _ok({
            "indexed": indexed,
            "errors": errors,
            "stats": stats,
        }, "Index rebuilt")

    except Exception as exc:
        logger.exception("RAG rebuild failed")
        return _err(f"Rebuild failed: {exc}", 500, "rebuild_error")


# ---------------------------------------------------------------------------
# GET /rag/stats — Index statistics
# ---------------------------------------------------------------------------
@app.route("/rag/stats", methods=["GET"])
def rag_stats() -> Response:
    """Get RAG index statistics."""
    rag = _get_rag()
    if rag is None:
        return _err("RAG not available", 503, "rag_unavailable")

    try:
        stats = rag.stats()
        return _ok(stats)
    except Exception as exc:
        logger.exception("RAG stats failed")
        return _err(f"Stats failed: {exc}", 500, "stats_error")


# ---------------------------------------------------------------------------
# POST /reason — LLM reasoning
# ---------------------------------------------------------------------------
@app.route("/reason", methods=["POST"])
def reason() -> Response:
    """LLM reasoning endpoint.

    Request body:
        {
            "task": "user task description",
            "context": { ... },          // optional
            "mode": "chat|classify",     // optional, default: chat
            "messages": [ ... ],         // for chat mode
            "max_tokens": 800,           // optional
            "temperature": 0.3           // optional
        }
    """
    data, err = _parse_json_body()
    if err:
        return _err(err)

    task = data.get("task", "")
    mode = data.get("mode", "chat")

    if not task and mode != "chat":
        return _err("'task' is required")

    try:
        llm = _get_llm()

        if mode == "chat":
            # Direct chat completion
            messages = data.get("messages", [])
            if not messages and task:
                messages = [{"role": "user", "content": task}]
            if not messages:
                return _err("'messages' or 'task' is required for chat mode")

            max_tokens = data.get("max_tokens", 800)
            temperature = data.get("temperature", 0.3)

            result = llm.chat(messages, max_tokens=max_tokens, temperature=temperature)
            return _ok({"response": result, "mode": "chat"})

        elif mode == "classify":
            # Quick task classification
            from ai.reasoner import quick_classify
            classification = quick_classify(task)
            return _ok({
                "classification": classification,
                "task": task,
                "mode": "classify",
            })

        elif mode == "reason":
            # Full reasoning with plan
            from ai.reasoner import reason as ai_reason
            context = data.get("context", {})
            plan = ai_reason(task, context)
            return _ok({"plan": plan, "mode": "reason"})

        else:
            return _err(f"Unknown mode: {mode}. Use: chat, classify, reason")

    except Exception as exc:
        logger.exception("Reasoning failed")
        return _err(f"Reasoning failed: {exc}", 500, "reasoning_error")


# ---------------------------------------------------------------------------
# POST /execute — Task execution with tools
# ---------------------------------------------------------------------------
@app.route("/execute", methods=["POST"])
def execute() -> Response:
    """Execute a task with tools.

    Request body (option A — direct tool execution):
        {
            "tool": "shell|browser|file_ops|search|media",
            "params": { ... }
        }

    Request body (option B — full plan execution):
        {
            "task": "user task description",
            "plan": { ... },      // optional, will auto-plan if not provided
            "auto_plan": true     // optional, default: true if no plan provided
        }
    """
    data, err = _parse_json_body()
    if err:
        return _err(err)

    try:
        # Option A: Direct tool execution
        if "tool" in data:
            tool_name = data["tool"]
            params = data.get("params", {})
            result = execute_single_tool(tool_name, params)
            return _ok(result)

        # Option B: Full task execution
        task = data.get("task", "")
        plan = data.get("plan")
        auto_plan = data.get("auto_plan", True)

        if not task and not plan:
            return _err("Either 'tool'/'params' or 'task' (with optional 'plan') is required")

        if plan:
            # Execute provided plan
            from ai.executor import execute_plan
            result = execute_plan(plan)
        elif auto_plan:
            # Plan and execute
            from ai.executor import execute_single
            result = execute_single(task)
        else:
            return _err("'plan' is required when auto_plan is false")

        return _ok(result)

    except Exception as exc:
        logger.exception("Execution failed")
        return _err(f"Execution failed: {exc}", 500, "execution_error")


def execute_single_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a single tool."""
    from ai.executor import execute_tool
    return execute_tool(tool_name, params)


# ---------------------------------------------------------------------------
# POST /plan — Task decomposition
# ---------------------------------------------------------------------------
@app.route("/plan", methods=["POST"])
def plan() -> Response:
    """Task decomposition endpoint.

    Request body:
        {
            "task": "user task description",
            "context": { ... }    // optional
        }
    """
    data, err = _parse_json_body()
    if err:
        return _err(err)

    task = data.get("task", "")
    if not task:
        return _err("'task' is required")

    try:
        from ai.reasoner import reason
        context = data.get("context", {})
        plan_result = reason(task, context)
        return _ok({"plan": plan_result})

    except Exception as exc:
        logger.exception("Planning failed")
        return _err(f"Planning failed: {exc}", 500, "planning_error")


# ---------------------------------------------------------------------------
# POST /learn — Extract skills from task result
# ---------------------------------------------------------------------------
@app.route("/learn", methods=["POST"])
def learn() -> Response:
    """Skills learning endpoint.

    Request body:
        {
            "task": "original task description",
            "result": { ... },       // execution result (must have success=true)
            "plan": { ... },         // optional, the plan that was executed
            "action": "learn|find|list|update_success|delete"
        }

    Actions:
        - learn: Extract skill from task result
        - find: Find matching skill for query
        - list: List all stored skills
        - update_success: Increment skill success count
        - delete: Delete a skill by id
    """
    data, err = _parse_json_body()
    if err:
        return _err(err)

    action = data.get("action", "learn")
    learner = _get_skills_learner()

    try:
        if action == "learn":
            task = data.get("task", "")
            result = data.get("result", {})
            plan = data.get("plan")

            if not task or not result:
                return _err("'task' and 'result' are required for learn action")

            skill = learner.learn_from_result(task, result, plan)
            if skill:
                return _ok({"skill": skill.to_dict(), "message": "Skill extracted and saved"})
            else:
                return _ok({"skill": None, "message": "No reusable pattern found"})

        elif action == "find":
            query = data.get("query", "")
            if not query:
                return _err("'query' is required for find action")
            skill = learner.find_skill(query)
            if skill:
                return _ok({"skill": skill.to_dict()})
            else:
                return _ok({"skill": None, "message": "No matching skill found"})

        elif action == "list":
            skills = learner.list_skills()
            return _ok({
                "skills": [s.to_dict() for s in skills],
                "count": len(skills),
            })

        elif action == "update_success":
            skill_id = data.get("skill_id", "")
            if not skill_id:
                return _err("'skill_id' is required for update_success action")
            skill = learner.update_success(skill_id)
            if skill:
                return _ok({"skill": skill.to_dict()})
            else:
                return _err("Skill not found", 404, "not_found")

        elif action == "delete":
            skill_id = data.get("skill_id", "")
            if not skill_id:
                return _err("'skill_id' is required for delete action")
            deleted = learner.delete_skill(skill_id)
            if deleted:
                return _ok({"message": "Skill deleted"})
            else:
                return _err("Skill not found", 404, "not_found")

        else:
            return _err(f"Unknown action: {action}. Use: learn, find, list, update_success, delete")

    except Exception as exc:
        logger.exception("Learning failed")
        return _err(f"Learning failed: {exc}", 500, "learning_error")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e) -> Response:
    return _err("Not found", 404, "not_found")


@app.errorhandler(405)
def method_not_allowed(e) -> Response:
    return _err("Method not allowed", 405, "method_not_allowed")


@app.errorhandler(500)
def internal_error(e) -> Response:
    return _err("Internal server error", 500, "internal_error")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def create_app() -> Flask:
    """Create and configure the Flask application."""
    # Initialize RAG pipeline eagerly on app creation
    if _rag_available:
        try:
            _get_rag()
            logger.info("RAG pipeline initialized during app creation")
        except Exception as exc:
             logger.warning("RAG init during app creation failed: %s", exc)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    logger.info("Starting Hermes AI Server on %s:%d", host, port)
    logger.info("Environment: LLM_API_BASE=%s, LLM_MODEL=%s",
                os.environ.get("LLM_API_BASE", "default"),
                os.environ.get("LLM_MODEL", "default"))

    app.run(host=host, port=port, debug=debug)
