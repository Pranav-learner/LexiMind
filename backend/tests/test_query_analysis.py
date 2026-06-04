"""Unit tests for the query analysis layer."""

from app.retrieval.query_analysis import analyze_query


def test_question_classification():
    a = analyze_query("How does the OS schedule processes?")
    assert a.query_type == "question"
    assert "schedule" in a.keywords
    dense_w, sparse_w = a.dense_sparse_weights()
    assert dense_w > sparse_w  # questions lean dense


def test_definition_classification_leans_sparse():
    a = analyze_query("definition of mutual exclusion")
    assert a.query_type == "definition"
    dense_w, sparse_w = a.dense_sparse_weights()
    assert sparse_w > dense_w


def test_comparison_and_summary():
    assert analyze_query("compare TCP vs UDP").query_type == "comparison"
    assert analyze_query("summarize chapter 3").query_type == "summary"


def test_keyword_heavy_query():
    a = analyze_query("faiss indexflatl2 cosine normalization")
    assert a.is_keyword_heavy
    assert a.query_type == "keyword"


def test_stopwords_excluded_from_keywords():
    a = analyze_query("what is the meaning of the word concurrency")
    assert "the" not in a.keywords
    assert "concurrency" in a.keywords
