import pytest

from tools.verify_phase9_search import build_corpus, nearest_rank


def test_benchmark_corpus_is_deterministic_and_has_a_cross_tenant_control() -> None:
    first, expected = build_corpus(10)
    second, _ = build_corpus(10)

    assert [record.record_id for record in first] == [record.record_id for record in second]
    assert len(first) == 11
    assert len({record.tenant_id for record in first}) == 2
    assert set(expected) == {"heart attack", "metformin", "penicillin", "मधुमेह"}


def test_nearest_rank_reports_small_sample_tail() -> None:
    assert nearest_rank([1.0, 2.0, 3.0, 100.0], 50) == 2.0
    assert nearest_rank([1.0, 2.0, 3.0, 100.0], 95) == 100.0


@pytest.mark.parametrize("record_count", [0, 9, 5_001])
def test_benchmark_rejects_unbounded_corpus(record_count: int) -> None:
    with pytest.raises(ValueError, match="between 10 and 5000"):
        build_corpus(record_count)
