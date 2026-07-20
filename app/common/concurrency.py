from concurrent.futures import ThreadPoolExecutor, as_completed


def map_concurrently(items: list, fn, max_workers: int = 8) -> dict:
    """Apply fn to each item concurrently, returning {item: result_or_exception}.

    An exception raised by fn for one item is captured as that item's value
    instead of propagating, so a single failure doesn't block the others.
    """
    if not items:
        return {}

    results = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
        future_to_item = {executor.submit(fn, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                results[item] = future.result()
            except Exception as exc:  # noqa: BLE001 - intentionally captured per item
                results[item] = exc
    return results
