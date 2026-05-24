#!/usr/bin/env python3
"""
RAG Demo Script
===============
Demonstrates the RAG pipeline in action.

Usage:
    cd ai-server
    python -m rag.demo
"""

from __future__ import annotations

import logging
import sys

# Ensure ai-server is on path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag_demo")


def main() -> None:
    from rag.rag_pipeline import RAGPipeline
    from rag.skills_indexer import SkillsIndexer

    print("=" * 60)
    print("  RAG Pipeline Demo")
    print("=" * 60)

    # Initialize pipeline
    pipeline = RAGPipeline()

    print(f"\n✅ Pipeline initialized")
    stats = pipeline.stats()
    print(f"   Embedding: {stats['embedding_provider']}")
    print(f"   Store: {stats['vector_store']}")
    print(f"   Reranker: {stats['reranker_strategy']}")

    # ---------------------------------------------------------------
    # 1. Index sample documents
    # ---------------------------------------------------------------
    print("\n--- Indexing Sample Documents ---\n")

    sample_docs = [
        {
            "text": "To set up a Python project, create a virtual environment with python -m venv, "
                "activate it, install dependencies with pip install -r requirements.txt, "
                "and run the project with python main.py",
            "metadata": {"topic": "python", "type": "tutorial", "source": "demo"},
        },
        {
            "text": "Docker deployment steps: Write a Dockerfile, build the image with docker build, "
                "tag it, push to registry, then pull and run on the target server",
            "metadata": {"topic": "docker", "type": "tutorial", "source": "demo"},
        },
        {
            "text": "Building a Flask REST API: Create Flask app, define routes with @app.route, "
                "return JSON with jsonify, handle errors with abort, and run with gunicorn",
            "metadata": {"topic": "flask", "type": "tutorial", "source": "demo"},
        },
        {
            "text": "Git workflow: Create feature branch, make commits, push to remote, "
                "open pull request, get code review, merge to main branch",
            "metadata": {"topic": "git", "type": "workflow", "source": "demo"},
        },
        {
            "text": "Machine learning pipeline: Collect data, preprocess features, split into "
                "train/test sets, train model, evaluate metrics, deploy to production",
            "metadata": {"topic": "ml", "type": "tutorial", "source": "demo"},
        },
    ]

    for doc in sample_docs:
        doc_id = pipeline.index_document(doc["text"], doc.get("metadata"))
        print(f"  📄 Indexed: {doc_id}")

    stats = pipeline.stats()
    print(f"\n  Total indexed: {stats['document_count']} documents")

    # ---------------------------------------------------------------
    # 2. Search for similar documents
    # ---------------------------------------------------------------
    print("\n--- Search Results ---\n")

    queries = [
        "How do I deploy a Python application?",
        "Setting up a new Flask project",
        "What's the best way to manage code changes?",
    ]

    for query in queries:
        print(f"  🔍 Query: \"{query}\"")
        results = pipeline.retrieve(query, top_k=3)
        for i, r in enumerate(results, 1):
            print(f"     {i}. [{r.id}] score={r.score:.3f}")
            text = r.text[:80] + "..." if len(r.text) > 80 else r.text
            print(f"        {text}")
        print()

    # ---------------------------------------------------------------
    # 3. Full RAG query (retrieve + augment)
    # ---------------------------------------------------------------
    print("--- Full RAG Query ---\n")

    rag_result = pipeline.query_with_rag("How do I set up Docker for deployment?", top_k=2)
    print(f"  Query: {rag_result['query']}")
    print(f"  Context docs: {rag_result['num_context']}")
    print(f"\n  Augmented prompt:\n{rag_result['augmented_prompt'][:500]}...")
    print()

    # ---------------------------------------------------------------
    # 4. Skills Indexer Demo
    # ---------------------------------------------------------------
    print("--- Skills Indexer Demo ---\n")

    skills_indexer = SkillsIndexer(pipeline=pipeline)

    sample_skills = [
        {
            "name": "python_project_setup",
            "trigger_keywords": ["python", "setup", "project", "virtualenv"],
            "steps": [
                "Create virtual environment",
                "Install dependencies",
                "Initialize git repo",
                "Create project structure",
            ],
            "result_template": "Project directory with venv, requirements.txt, and git initialized",
        },
        {
            "name": "docker_deploy",
            "trigger_keywords": ["docker", "deploy", "container", "image"],
            "steps": [
                "Write Dockerfile",
                "Build Docker image",
                "Push to registry",
                "Deploy to server",
            ],
            "result_template": "Running Docker container on target server",
        },
    ]

    for skill in sample_skills:
        doc_id = skills_indexer.index_skill(skill, filename=f"{skill['name']}.json")
        print(f"  📄 Indexed skill: {skill['name']} -> {doc_id}")

    # Search for skills
    skill_results = skills_indexer.search("How do I set up a new Python project?", top_k=2)
    print(f"\n  Skill search: 'How do I set up a new Python project?'")
    for i, r in enumerate(skill_results, 1):
        print(f"     {i}. [{r.id}] score={r.score:.3f} - {r.text[:60]}...")

    # ---------------------------------------------------------------
    # 5. Final stats
    # ---------------------------------------------------------------
    print("\n--- Final Stats ---\n")
    stats = pipeline.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("  Demo complete! ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
