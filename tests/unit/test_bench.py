from bench.common import percentile


def test_measured_percentiles_empty_and_ordered():
    assert percentile([], 95) is None
    assert percentile([3, 1, 2], 50) == 2
    assert percentile(list(range(101)), 95) == 95
    assert percentile([7], 99) == 7
