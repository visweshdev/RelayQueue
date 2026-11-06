from forgequeue.core.repo import Repository


async def promote_due(repo: Repository) -> int:
    total = 0
    while True:
        count = await repo.promote()
        total += count
        if count < repo.settings.batch_size:
            return total
