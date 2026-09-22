"""A1 page selection and statistical estimates use public, reproducible inputs."""

from signals.acquisition_programs.census_sampling import (
    public_seed,
    select_pages,
    wilson_interval,
)


def test_nine_pages_span_the_accessible_depth_without_recalling_page_one() -> None:
    seed = public_seed("synthetic-permit-a1")
    pages = select_pages(partition_id="synthetic-partition", total_pages=500, seed=seed)
    assert len(pages) == len({item.page for item in pages}) == 9
    assert all(2 <= item.page <= 500 for item in pages)
    assert pages[0].block_start == 2
    assert pages[-1].block_end == 500
    assert pages[-1].page > 400
    assert pages == select_pages(partition_id="synthetic-partition", total_pages=500, seed=seed)
    assert pages != select_pages(
        partition_id="synthetic-partition", total_pages=500,
        seed=public_seed("another-permit-a1"),
    )


def test_short_partitions_and_apollo_page_cap_never_duplicate_pages() -> None:
    seed = public_seed("synthetic-permit-a1")
    assert tuple(item.page for item in select_pages(
        partition_id="short", total_pages=4, seed=seed,
    )) == (2, 3, 4)
    assert select_pages(partition_id="empty", total_pages=1, seed=seed) == ()
    assert max(item.page for item in select_pages(
        partition_id="capped", total_pages=9_999, seed=seed,
    )) <= 500


def test_wilson_interval_is_bounded_and_contains_observed_rate() -> None:
    low, high = wilson_interval(46, 223)
    assert 0 < low < 46 / 223 < high < 1
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert wilson_interval(0, 25)[0] == 0.0
    assert wilson_interval(25, 25)[1] == 1.0
