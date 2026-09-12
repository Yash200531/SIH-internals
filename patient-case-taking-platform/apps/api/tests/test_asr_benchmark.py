from tools.benchmark_asr import nearest_rank_percentile, normalize, word_error_rate


def test_normalize_handles_hindi_punctuation_and_case() -> None:
    assert normalize("बुखार है। FEVER!") == ["बुखार", "है", "fever"]


def test_word_error_rate_counts_substitution_insertion_and_deletion() -> None:
    assert word_error_rate("मुझे बुखार है", "मुझे तेज बुखार") == 2 / 3
    assert word_error_rate("patient has fever", "patient has fever") == 0.0


def test_nearest_rank_percentile_includes_small_sample_tail() -> None:
    assert nearest_rank_percentile([1, 2, 3, 4, 5, 6, 7, 8, 9], 0.95) == 9
